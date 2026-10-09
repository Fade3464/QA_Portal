import logging
import uuid
from django.core.cache import cache
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import NotFound, APIException
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from .access import require_ai_access, scope_digest
from .models import AIConversation, AIMessage
from .orchestrator import run_ai
from .legacy_orchestrator import run_ai as legacy_run_ai
from .investigation import run_ai as v3_run_ai
from .provider import AIProviderError
from .registry import tool_names

logger = logging.getLogger(__name__)


class AIThrottle(UserRateThrottle):
    scope = 'ai_chat'


class ChatRequest(serializers.Serializer):
    message = serializers.CharField(max_length=2000, trim_whitespace=True, allow_blank=False)
    conversation_id = serializers.UUIDField(required=False)


class AIEnabledPermission(IsAuthenticated):
    def has_permission(self, request, view):
        permitted = super().has_permission(request, view)
        if permitted:
            require_ai_access(request.user)
        return permitted


def _get_conversation(user, pk):
    conversation = AIConversation.objects.filter(pk=pk, user=user).first()
    if not conversation or conversation.scope_digest != scope_digest(user):
        raise NotFound('Conversation not found.')
    return conversation


class AIMetadataView(APIView):
    permission_classes = [AIEnabledPermission]

    def get(self, request):
        return Response({'enabled': settings.AI_ENABLED,
                         'provider_configured': bool(settings.AI_LLM_MODEL and settings.AI_LLM_BASE_URL),
                         'engine_version': settings.AI_ENGINE_VERSION,
                         'tools': tool_names(), 'capabilities': ['read_only_qa_analytics', 'semantic_query_planning', 'verified_review_backlog', 'v3_bounded_investigation'],
                         'actions_enabled': False})


class AIConversationListView(APIView):
    permission_classes = [AIEnabledPermission]

    def get(self, request):
        digest = scope_digest(request.user)
        records = AIConversation.objects.filter(user=request.user, scope_digest=digest)[:30]
        return Response({'conversations': [{'id': str(c.pk), 'title': c.title,
                                           'updated_at': c.updated_at.isoformat()} for c in records]})


class AIConversationDetailView(APIView):
    permission_classes = [AIEnabledPermission]

    def get(self, request, pk):
        conversation = _get_conversation(request.user, pk)
        messages = conversation.messages.all().order_by('-created_at')[:50]
        return Response({'id': str(conversation.pk), 'messages': [
            {'id': str(m.pk), 'role': m.role, 'content': m.content,
             'evidence': m.evidence if m.role == AIMessage.Role.ASSISTANT else [],
             'tools_used': m.tools_used if m.role == AIMessage.Role.ASSISTANT else [],
             'interpretation': m.interpretation if m.role == AIMessage.Role.ASSISTANT else {},
             'warnings': m.warnings if m.role == AIMessage.Role.ASSISTANT else [],
             'created_at': m.created_at.isoformat()} for m in reversed(list(messages))]})

    def delete(self, request, pk):
        _get_conversation(request.user, pk).delete()
        return Response(status=204)


class ConversationBusy(APIException):
    status_code = 409
    default_detail = 'This conversation already has a request in progress.'


class AIChatView(APIView):
    permission_classes = [AIEnabledPermission]
    throttle_classes = [AIThrottle]

    def post(self, request):
        if not settings.AI_ENABLED:
            return Response({'detail': 'AI assistant is disabled by configuration.'}, status=503)
        request_data = ChatRequest(data=request.data)
        request_data.is_valid(raise_exception=True)
        payload = request_data.validated_data
        conversation = None
        if payload.get('conversation_id'):
            conversation = _get_conversation(request.user, payload['conversation_id'])
        history = []
        if conversation:
            records = list(conversation.messages.order_by('-created_at')[:4])
            history = [{'role': row.role, 'content': row.content[:650]} for row in reversed(records)]
        # Do not allow two concurrent requests to the same conversation to interleave turns.
        # Production cache is Redis; this atomic ADD is not a network request to the LLM.
        lock_key = f'qa-ai:conversation:{conversation.pk}' if conversation else None
        lock_token = str(uuid.uuid4())
        if lock_key and not cache.add(lock_key, lock_token, timeout=300):
            raise ConversationBusy()
        request_scope = scope_digest(request.user)
        try:
            # Never hold SQL row locks during network inference.
            engine = {'v1': legacy_run_ai, 'v2': run_ai, 'v3': v3_run_ai}[settings.AI_ENGINE_VERSION]
            # Interpret calendar references using the user's branch timezone.
            user_tz = (request.user.branch.timezone if request.user.branch_id else settings.TIME_ZONE)
            with timezone.override(user_tz):
                result = engine(request.user, payload['message'], conversation=conversation, history=history)
            # Permissions may change while the model is running. Never persist or
            # return a completed analysis under a stale authorization fingerprint.
            request.user.refresh_from_db()
            require_ai_access(request.user)
            if scope_digest(request.user) != request_scope:
                return Response({'detail': 'Your reporting access changed during this request. Start a new conversation.'}, status=409)
            if not conversation:
                conversation = AIConversation.objects.create(user=request.user, scope_digest=request_scope,
                                                              title=payload['message'][:120])
            with transaction.atomic():
                AIMessage.objects.create(conversation=conversation, role=AIMessage.Role.USER, content=payload['message'])
                AIMessage.objects.create(conversation=conversation, role=AIMessage.Role.ASSISTANT,
                                         content=result['answer'], evidence=result.get('evidence', []),
                                         tools_used=result.get('tools_used', []),
                                         interpretation=result.get('interpretation', {}),
                                         warnings=result.get('warnings', []))
                AIConversation.objects.filter(pk=conversation.pk).update(
                    updated_at=timezone.now(), context_state=result.get('context_state', {}))
            return Response({'conversation_id': str(conversation.pk),
                             **{k:v for k,v in result.items() if k != 'context_state'}})
        except AIProviderError:
            logger.warning('AI inference failed for user=%s', request.user.pk)
            return Response({'detail': 'The AI inference service is unavailable or unable to answer safely.'}, status=503)
        finally:
            # Include the history/state commit in the protected interval; another
            # turn must not acquire this conversation before its predecessor saves.
            if lock_key and cache.get(lock_key) == lock_token:
                cache.delete(lock_key)

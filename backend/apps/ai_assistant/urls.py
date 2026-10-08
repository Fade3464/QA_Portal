from django.urls import path
from .views import AIChatView, AIConversationDetailView, AIConversationListView, AIMetadataView

urlpatterns = [
    path('metadata/', AIMetadataView.as_view(), name='ai-metadata'),
    path('chat/', AIChatView.as_view(), name='ai-chat'),
    path('conversations/', AIConversationListView.as_view(), name='ai-conversations'),
    path('conversations/<uuid:pk>/', AIConversationDetailView.as_view(), name='ai-conversation-detail'),
]

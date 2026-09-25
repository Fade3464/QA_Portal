from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.http import FileResponse
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Feedback, FeedbackImage
from .permissions import IsSystemAdministrator
from .services import MAX_FEEDBACK_IMAGES, prepare_feedback_image


class FeedbackInputSerializer(serializers.Serializer):
    message = serializers.CharField(max_length=3000, trim_whitespace=True)


class FeedbackReviewSerializer(serializers.Serializer):
    reviewed = serializers.BooleanField()


def serialize_feedback(feedback):
    return {
        "id": str(feedback.pk),
        "message": feedback.message,
        "status": feedback.status,
        "user": {
            "id": str(feedback.user_id),
            "name": feedback.user.full_name,
            "email": feedback.user.email,
            "role": feedback.user.get_role_display(),
            "company": feedback.user.company.name if feedback.user.company_id else "System-wide",
            "branch": feedback.user.branch.name if feedback.user.branch_id else "All organizations",
        },
        "images": [
            {
                "id": str(image.pk),
                "name": image.original_name,
                "url": f"/api/v1/feedback/{feedback.pk}/images/{image.pk}/",
            }
            for image in feedback.images.all()
        ],
        "reviewed_by": feedback.reviewed_by.full_name if feedback.reviewed_by_id else "",
        "reviewed_at": feedback.reviewed_at.isoformat() if feedback.reviewed_at else None,
        "created_at": feedback.created_at.isoformat(),
        "updated_at": feedback.updated_at.isoformat(),
    }


class FeedbackSubmitView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = FeedbackInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        uploads = request.FILES.getlist("images")
        if len(uploads) > MAX_FEEDBACK_IMAGES:
            raise serializers.ValidationError(
                {"images": f"Attach no more than {MAX_FEEDBACK_IMAGES} images."}
            )

        prepared = []
        try:
            for upload in uploads:
                filename, content = prepare_feedback_image(upload)
                prepared.append((upload.name[:255], filename, content))
        except DjangoValidationError as exc:
            raise DRFValidationError(
                exc.message_dict if hasattr(exc, "message_dict") else exc.messages
            ) from exc

        saved_images = []
        try:
            with transaction.atomic():
                feedback = Feedback.objects.create(
                    user=request.user, message=serializer.validated_data["message"]
                )
                for original_name, filename, content in prepared:
                    image = FeedbackImage(feedback=feedback, original_name=original_name)
                    image.image.save(filename, content, save=True)
                    saved_images.append(image)
        except Exception:
            for image in saved_images:
                if image.image:
                    image.image.delete(save=False)
            raise

        return Response(
            {"id": str(feedback.pk), "status": feedback.status},
            status=status.HTTP_201_CREATED,
        )


class FeedbackAdminListView(APIView):
    permission_classes = [IsSystemAdministrator]

    def get(self, request):
        feedback = (
            Feedback.objects.select_related(
                "user", "user__company", "user__branch", "reviewed_by"
            )
            .prefetch_related("images")
            .order_by("-created_at")[:200]
        )
        return Response({"results": [serialize_feedback(item) for item in feedback]})


class FeedbackAdminDetailView(APIView):
    permission_classes = [IsSystemAdministrator]

    def patch(self, request, pk):
        serializer = FeedbackReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        feedback = Feedback.objects.filter(pk=pk).first()
        if not feedback:
            return Response(status=status.HTTP_404_NOT_FOUND)

        if serializer.validated_data["reviewed"]:
            feedback.status = Feedback.Status.REVIEWED
            feedback.reviewed_by = request.user
            feedback.reviewed_at = timezone.now()
        else:
            feedback.status = Feedback.Status.OPEN
            feedback.reviewed_by = None
            feedback.reviewed_at = None
        feedback.save(
            update_fields=["status", "reviewed_by", "reviewed_at", "updated_at"]
        )
        feedback = Feedback.objects.select_related(
            "user", "user__company", "user__branch", "reviewed_by"
        ).prefetch_related("images").get(pk=feedback.pk)
        return Response(serialize_feedback(feedback))


class FeedbackImageView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, feedback_id, image_id):
        image = FeedbackImage.objects.select_related("feedback").filter(
            pk=image_id, feedback_id=feedback_id
        ).first()
        if not image:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if not request.user.is_superuser and image.feedback.user_id != request.user.pk:
            return Response(status=status.HTTP_404_NOT_FOUND)
        try:
            response = FileResponse(image.image.open("rb"), content_type="image/webp")
        except FileNotFoundError:
            return Response(status=status.HTTP_404_NOT_FOUND)
        response["Cache-Control"] = "private, max-age=3600"
        response["X-Content-Type-Options"] = "nosniff"
        return response

from django.http import JsonResponse


def not_found(request, exception=None):
    return JsonResponse({"message": "Not found."}, status=404)


def server_error(request):
    # Never echo exception details: they are logged server-side by Django.
    return JsonResponse({"message": "Something went wrong. Please try again."}, status=500)

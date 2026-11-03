from django.conf import settings
from rest_framework.response import Response
from rest_framework.views import APIView


class NetworkView(APIView):
    """The names this machine is reached by on the network (LAN_HOSTS), so the
    board can hand out a follow-view link that works on a tablet. The browser
    can't learn them itself, and in Docker neither can the server: it sees the
    container's addresses. These are the hosts ALLOWED_HOSTS and the allowed
    origins accept, so a link built from one of them opens."""

    def get(self, request):
        return Response({"hosts": settings.LAN_HOSTS})

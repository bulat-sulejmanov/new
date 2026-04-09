from django.db import connections
from django.db.utils import OperationalError
from django.http import HttpResponse, JsonResponse
from django.template.loader import render_to_string
from django.utils.deprecation import MiddlewareMixin


class DatabaseUnavailableMiddleware(MiddlewareMixin):
    """Показывает понятную страницу, если PostgreSQL недоступен."""

    DB_ERROR_MARKERS = (
        'connection timeout expired',
        'server closed the connection unexpectedly',
        'could not connect to server',
        'connection refused',
        'connection failed',
        'terminating connection',
    )

    def _is_database_error(self, exception):
        if isinstance(exception, OperationalError):
            return True
        message = str(exception).lower()
        return any(marker in message for marker in self.DB_ERROR_MARKERS)

    def _build_response(self, request):
        connections.close_all()
        payload = {
            'ok': False,
            'error': 'database_unavailable',
            'message': 'Нет подключения к базе данных. Проверьте PostgreSQL и повторите попытку.',
        }

        if request.path.startswith('/admin/') or request.path.startswith('/api/'):
            return JsonResponse(payload, status=503)

        accepts_json = 'application/json' in request.headers.get('Accept', '')
        if accepts_json:
            return JsonResponse(payload, status=503)

        html = render_to_string(
            'errors/database_unavailable.html',
            {'retry_url': request.get_full_path() or '/'},
        )
        return HttpResponse(html, status=503)

    def process_exception(self, request, exception):
        if self._is_database_error(exception):
            return self._build_response(request)
        return None

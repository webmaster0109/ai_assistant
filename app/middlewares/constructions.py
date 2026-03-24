from app.models import WebsiteSettings
from django.http import HttpResponse

class WebsiteUnderConstructionMiddleware:
  def __init__(self, get_response):
    self.get_response = get_response
  
  def __call__(self, request):
    settings = WebsiteSettings.objects.filter(maintainance_mode=True).first()
    if settings and not request.path.startswith('/admin/'):
      return HttpResponse("The website is currently under construction. Please check back later.")
    response = self.get_response(request)
    return response
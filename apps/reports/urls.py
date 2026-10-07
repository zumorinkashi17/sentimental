from django.urls import path
from django.views.generic import TemplateView #temporary rapud ni
from . import views

app_name = 'reports'

urlpatterns = [
    path('generate/', views.generate_view, name='generate'),
    path('export-pdf/<int:report_id>/', views.export_pdf_view, name='export_pdf'),

    #temporaryyy rani para makita nko dagway sa forecast html
    path('test-forecast/', TemplateView.as_view(template_name='reports/forecast_pdf_report.html')),
]
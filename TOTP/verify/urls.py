from django.urls import path
from . import views

# Setting an app_name defines a namespace, making it easier to reverse URLs in templates
app_name = 'verify'

urlpatterns = [
    path('', views.helpdesk_dashboard, name='dashboard'),
    path('enroll/<int:user_id>/', views.generate_enrollment_qr, name='enroll_user'),
    path('check/<int:user_id>/', views.verify_caller, name='verify_caller'),
    path('add-employee/', views.add_employee, name='add_employee'),
    path('unenroll/<int:user_id>/', views.unenroll_employee, name='unenroll'),]

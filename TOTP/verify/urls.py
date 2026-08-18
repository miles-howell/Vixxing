from django.urls import path
from . import views

# Setting an app_name defines a namespace, making it easier to reverse URLs in templates
app_name = 'verify'

urlpatterns = [
    path('', views.helpdesk_dashboard, name='dashboard'),
    path('enroll/<int:user_id>/', views.generate_enrollment_qr, name='enroll_user'),
    path('check/<int:user_id>/', views.verify_caller, name='verify_caller'),
    path('add-employee/', views.add_employee, name='add_employee'),
    path('unenroll/<int:user_id>/', views.unenroll_employee, name='unenroll'),
    path('delete/<int:user_id>/', views.delete_employee, name='delete_employee'),
    path('export-employees/', views.export_employees_csv, name='export_employees'),
    path('import-employees/', views.import_employees_csv, name='import_employees'),
    path('bulk-enroll/', views.bulk_enroll_employees, name='bulk_enroll'),
    path('bulk-reenroll/', views.bulk_reenroll_employees, name='bulk_reenroll'),
    path('bulk-unenroll/', views.bulk_unenroll_employees, name='bulk_unenroll'),
    path('bulk-delete/', views.bulk_delete_employees, name='bulk_delete'),
]

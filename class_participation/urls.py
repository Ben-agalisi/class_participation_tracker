from django.contrib import admin
from django.urls import include, path
from participation.admin import add_marks_view, student_export_csv, student_search_api
from participation.views import staff_signup_view, student_registration_view

urlpatterns = [
    path('', student_registration_view, name='home'),
    path('register/', student_registration_view, name='student_registration'),
    path('staff-signup/', staff_signup_view, name='staff_signup'),
    path('accounts/', include('django.contrib.auth.urls')),
    path('admin/add-marks/', add_marks_view, name='add_marks'),
    path('admin/student-search/', student_search_api, name='student_search_api'),
    path('admin/export-students/', student_export_csv, name='student_export_csv'),
    
    path('admin/', admin.site.urls),
]
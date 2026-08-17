from django.db import models
from django.contrib.auth.models import User


# Create your models here.
class EmployeeMFA(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="employeemfa")
    mfa_secret = models.CharField(max_length=64, blank=True, null=True)
    is_enrolled = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.user.username} - MFA Enrolled: {self.is_enrolled}"

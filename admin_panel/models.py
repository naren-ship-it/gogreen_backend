from django.db import models

# Create your models here.
class FreeText(models.Model):
    text = models.TextField()
    style = models.JSONField(default=dict, blank=True)
    bg_image = models.ImageField(upload_to='free_text_bg_images/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    def __str__(self):
        return self.text
    

class FreeTextDraft(models.Model):
    text = models.TextField(blank=True, default="")
    style = models.JSONField(default=dict, blank=True)
    bg_image = models.ImageField(
        upload_to='free_text_drafts/',
        blank=True,
        null=True
    )
    updated_at = models.DateTimeField(auto_now=True)

    def _str_(self):
        return self.text or "Free Text Draft"
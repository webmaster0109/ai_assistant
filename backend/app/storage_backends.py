from django.conf import settings
from storages.backends.s3 import S3Storage


class CloudflareR2Storage(S3Storage):
    bucket_name = settings.R2_BUCKET_NAME
    endpoint_url = settings.R2_ENDPOINT_URL
    access_key = settings.R2_ACCESS_KEY_ID
    secret_key = settings.R2_SECRET_ACCESS_KEY
    region_name = getattr(settings, "AWS_S3_REGION_NAME", "auto")
    signature_version = getattr(settings, "AWS_S3_SIGNATURE_VERSION", "s3v4")
    addressing_style = getattr(settings, "AWS_S3_ADDRESSING_STYLE", "path")
    default_acl = None
    file_overwrite = False
    querystring_auth = getattr(settings, "AWS_QUERYSTRING_AUTH", True)
    custom_domain = getattr(settings, "R2_PUBLIC_MEDIA_DOMAIN", "")


class CloudflareR2MediaStorage(CloudflareR2Storage):
    location = getattr(settings, "R2_MEDIA_LOCATION", "")

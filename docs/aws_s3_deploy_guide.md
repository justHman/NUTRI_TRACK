Để upgrade lên S3/DynamoDB sau này
Chỉ cần thay 2 hàm này trong 

USDA.py
:


_load_disk_cache()
 → pull từ S3 s3.get_object(...)

_save_disk_cache(cache)
 → push lên S3 s3.put_object(...)
Không cần đụng vào business logic nào cả.
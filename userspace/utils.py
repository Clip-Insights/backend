from account.models import User
from .models import File

def storage_info(user_id):
    print("user_id", user_id)
    user = User.objects.get(id=user_id)
    files = File.objects.filter(user_id=user_id)
    allowed_space = user.allocated_space
    used_space = 0
    for file in files:
        used_space += file.size
    remaining_space = allowed_space - used_space
    print("used_space", used_space)
    return {"used_space": used_space, "allowed_space": allowed_space, "remaining_space": remaining_space}
    
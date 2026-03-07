# -*- coding: utf-8 -*-
"""
AES加密工具，用于本地加密存储MySQL密码
使用AES-CBC模式，密钥由机器码派生
"""
import os
import base64
import hashlib

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

# 固定IV（16字节）
_IV = b"AiKeFuClient2024"

# 派生密钥
def _get_key() -> bytes:
    """从机器特征派生32字节AES密钥"""
    machine_id = _get_machine_id()
    return hashlib.sha256(machine_id.encode("utf-8")).digest()


def _get_machine_id() -> str:
    """获取机器唯一标识"""
    # 尝试多种方式获取机器ID
    candidates = []

    # Windows: 从注册表读取MachineGuid
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
        )
        guid, _ = winreg.QueryValueEx(key, "MachineGuid")
        candidates.append(guid)
    except Exception:
        pass

    # Linux: 读取 /etc/machine-id
    try:
        with open("/etc/machine-id", "r") as f:
            candidates.append(f.read().strip())
    except Exception:
        pass

    # macOS: 使用 ioreg
    try:
        import subprocess
        result = subprocess.run(
            ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
            capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.splitlines():
            if "IOPlatformUUID" in line:
                candidates.append(line.split('"')[-2])
                break
    except Exception:
        pass

    if candidates:
        return candidates[0]

    # 后备方案：使用用户主目录路径哈希
    return hashlib.md5(os.path.expanduser("~").encode()).hexdigest()


def encrypt_password(plain_password: str) -> str:
    """加密密码，返回base64编码字符串"""
    key = _get_key()
    cipher = AES.new(key, AES.MODE_CBC, _IV)
    encrypted = cipher.encrypt(pad(plain_password.encode("utf-8"), AES.block_size))
    return base64.b64encode(encrypted).decode("utf-8")


def decrypt_password(encrypted_b64: str) -> str:
    """解密base64编码的加密密码"""
    key = _get_key()
    encrypted = base64.b64decode(encrypted_b64.encode("utf-8"))
    cipher = AES.new(key, AES.MODE_CBC, _IV)
    decrypted = unpad(cipher.decrypt(encrypted), AES.block_size)
    return decrypted.decode("utf-8")

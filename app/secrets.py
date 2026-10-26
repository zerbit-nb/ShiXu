"""Protect persisted API keys with the current Windows user's DPAPI."""
import base64
import ctypes
import os
from ctypes import wintypes


class Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_byte))]


def transform(data: bytes, decrypt: bool = False) -> bytes:
    if os.name != 'nt':
        raise ValueError('非 Windows 环境请通过 OPENAI_API_KEY / DEEPSEEK_API_KEY 环境变量配置密钥。')
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    output = Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise ValueError('无法使用当前 Windows 用户保护或读取 API Key，请重新填写。')
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        kernel.LocalFree(ctypes.cast(output.data, ctypes.c_void_p))


def protect(key: str) -> str:
    return base64.b64encode(transform(key.encode('utf-8'))).decode('ascii') if key else ''


def unprotect(value: str) -> str:
    return transform(base64.b64decode(value), decrypt=True).decode('utf-8') if value else ''

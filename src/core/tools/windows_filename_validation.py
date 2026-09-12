from ..schemas.op_result import OpResult, ok, err

def validate_windows_filename(v: str) -> OpResult[None]:
    """
    校验合法的 Windows 文件名、
    """

    if not isinstance(v, (str, int, float)):
        return err(f"filename must be a string, got {type(v).__name__}")
        
    v = str(v).strip()
    
    if not v:
        return err("filename cannot be empty or pure whitespace(s)")
    
    # Windows 文件名禁止字符
    invalid_chars = {'\\', '/', ':', '*', '?', '"', '<', '>', '|'}
    if any(c in invalid_chars for c in v):
        return err(f"filename '{v}' cannot contain invalid characters: \\ / : * ? \" < > |")
        
    # 禁止保留名称
    reserved_names = {
        'CON', 'PRN', 'AUX', 'NUL',
        'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9',
        'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9'
    }
    if v.upper() in reserved_names:
        return err(f"filename '{v}' cannot be a reserved system name")
        
    return ok()

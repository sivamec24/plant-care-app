"""
File upload validation and processing utilities.

Provides secure file upload handling with:
- Extension validation
- Content validation (magic number checking)
- Size limits
- Protection against double extension attacks
"""

from __future__ import annotations
from typing import Tuple, Optional
from PIL import Image
from io import BytesIO
import os

# Security: Allowed image file extensions
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

# Security: Maximum file size (5MB)
MAX_FILE_SIZE = 5 * 1024 * 1024


def allowed_file(filename: str) -> bool:
    """
    Check if filename has an allowed extension and no dangerous double extensions.

    Security features:
    - Validates against whitelist of safe extensions
    - Prevents double extension attacks (e.g., 'image.php.jpg')
    - Prevents path traversal attempts

    Args:
        filename: The filename to validate

    Returns:
        True if filename is safe, False otherwise

    Examples:
        >>> allowed_file('photo.jpg')
        True
        >>> allowed_file('photo.php.jpg')  # Double extension attack
        False
        >>> allowed_file('../../../etc/passwd')
        False
    """
    if not filename or '.' not in filename:
        return False

    # Security: Prevent path traversal
    if '..' in filename or '/' in filename or '\\' in filename:
        return False

    # Get final extension
    ext = filename.rsplit('.', 1)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return False

    # Security: Check for double extension attack (e.g., image.php.jpg)
    # Count dots - if more than 1, check second-to-last extension isn't dangerous
    parts = filename.lower().split('.')
    if len(parts) > 2:
        # Check second-to-last extension isn't a dangerous executable type
        dangerous_exts = {
            'php', 'phtml', 'php3', 'php4', 'php5',
            'exe', 'sh', 'bat', 'cmd', 'com',
            'js', 'py', 'rb', 'pl', 'cgi',
            'asp', 'aspx', 'jsp'
        }
        if parts[-2] in dangerous_exts:
            return False

    return True


def validate_image_content(file_bytes: bytes) -> bool:
    """
    Validate that file content is actually a valid image.

    Security: This prevents malicious files with spoofed extensions by checking
    the actual file content (magic numbers/file signature) using PIL.

    Args:
        file_bytes: The file content as bytes

    Returns:
        True if valid image, False otherwise

    Examples:
        >>> with open('valid_image.jpg', 'rb') as f:
        ...     validate_image_content(f.read())
        True
        >>> validate_image_content(b'<script>alert("xss")</script>')
        False
    """
    try:
        img = Image.open(BytesIO(file_bytes))
        img.verify()  # Verify it's a valid image
        return True
    except Exception:
        return False


def validate_upload_file(
    file,
    max_size: int = MAX_FILE_SIZE
) -> Tuple[bool, Optional[str], Optional[bytes]]:
    """
    Comprehensive file upload validation.

    Performs all security checks:
    1. File exists and has a name
    2. Extension is allowed
    3. File size is within limits
    4. File content is a valid image (magic number check)

    Args:
        file: FileStorage object from Flask request.files
        max_size: Maximum allowed file size in bytes (default: 5MB)

    Returns:
        (is_valid, error_message, file_bytes)
        - is_valid: True if file passes all checks
        - error_message: None if valid, error string if invalid
        - file_bytes: File content as bytes if valid, None if invalid

    Usage:
        >>> file = request.files.get('photo')
        >>> is_valid, error, file_bytes = validate_upload_file(file)
        >>> if not is_valid:
        ...     flash(error, 'error')
        ...     return redirect(...)
        >>> # Proceed with upload using file_bytes
    """
    # Check if file exists and has a filename
    if not file or not file.filename:
        return False, None, None  # No file provided (not an error, just skip)

    # Check file extension
    if not allowed_file(file.filename):
        return False, "Invalid file type. Only images (PNG, JPG, GIF, WebP) are allowed.", None

    # Check file size
    file.seek(0, os.SEEK_END)
    file_length = file.tell()
    if file_length > max_size:
        max_mb = max_size / (1024 * 1024)
        return False, f"Photo must be less than {max_mb:.0f}MB.", None

    # Read file content
    file.seek(0)
    file_bytes = file.read()

    # Validate actual file content (prevents malicious files with spoofed extensions)
    if not validate_image_content(file_bytes):
        return False, "Invalid image file. Please upload a valid image.", None

    return True, None, file_bytes

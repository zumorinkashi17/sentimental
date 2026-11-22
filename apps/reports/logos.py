import logging
import os
from urllib.parse import quote

from django.core.exceptions import ValidationError
from django.templatetags.static import static
from PIL import Image, UnidentifiedImageError
from supabase import create_client


LOGO_SLOTS = ('left', 'center', 'right', 'extra1', 'extra2')

LOGO_DEFAULTS = {
    'left': {'path': 'images/doh-logo.png', 'alt': 'DOH', 'css_class': ''},
    'center': {'path': 'images/tpcb-logo.png', 'alt': 'Tawag Paglaum', 'css_class': 'scale-[1.32]'},
    'right': {'path': 'images/vsmmc-logo.png', 'alt': 'VSMMC', 'css_class': ''},
}

BUCKET_NAME = 'image-bucket'
LOGO_PREFIX = 'report-logos'
ALLOWED_EXTENSIONS = {'png', 'jpg'}
FORMAT_EXTENSIONS = {'PNG': 'png', 'JPEG': 'jpg'}
CONTENT_TYPES = {'png': 'image/png', 'jpg': 'image/jpeg'}
MAX_LOGO_BYTES = 2 * 1024 * 1024

logger = logging.getLogger(__name__)
_client = None


def _get_client():
    global _client
    if _client is None:
        url = os.environ.get('SUPABASE_URL')
        key = os.environ.get('SUPABASE_KEY')
        if not url or not key:
            raise RuntimeError('Supabase credentials are not configured.')
        _client = create_client(url, key)
    return _client


def _bucket():
    return _get_client().storage.from_(BUCKET_NAME)


def _object_folder(report_id):
    return f'{LOGO_PREFIX}/{int(report_id)}'


def _ensure_prefixed(key):
    if not key.startswith(f'{LOGO_PREFIX}/') or '..' in key.split('/'):
        raise ValidationError('Invalid logo path.')


def _object_key(report_id, slot, extension):
    if slot not in LOGO_SLOTS:
        raise ValidationError('Invalid logo slot.')
    if extension not in ALLOWED_EXTENSIONS:
        raise ValidationError('Logo must be a PNG or JPG image.')
    key = f'{_object_folder(report_id)}/{slot}.{extension}'
    _ensure_prefixed(key)
    return key


def _list_objects(report_id, soft=False):
    folder = _object_folder(report_id)
    try:
        return _bucket().list(folder) or []
    except Exception:
        if soft:
            logger.exception('Unable to list report logos for report %s.', report_id)
            return []
        raise


def _slot_objects(report_id, soft=False):
    objects = {}
    for item in _list_objects(report_id, soft=soft):
        name = str(item.get('name') or '').rsplit('/', 1)[-1]
        base, separator, extension = name.rpartition('.')
        if not separator:
            continue
        extension = extension.lower()
        if extension == 'jpeg':
            extension = 'jpg'
        if base not in LOGO_SLOTS or extension not in ALLOWED_EXTENSIONS:
            continue
        key = f'{_object_folder(report_id)}/{name}'
        _ensure_prefixed(key)
        updated_at = str(item.get('updated_at') or item.get('created_at') or '')
        current = objects.get(base)
        if current is None or updated_at > current['updated_at']:
            objects[base] = {'key': key, 'name': name, 'updated_at': updated_at}
    return objects


def _public_url(key, updated_at):
    url = _bucket().get_public_url(key)
    if updated_at:
        separator = '&' if '?' in url else '?'
        url = f"{url}{separator}v={quote(updated_at, safe='')}"
    return url


def get_logo_slots(report_id):
    """Return all five slots, including empty optional slots (url is None)."""
    objects = _slot_objects(report_id, soft=True)
    slots = []
    for slot in LOGO_SLOTS:
        default = LOGO_DEFAULTS.get(slot)
        custom = objects.get(slot)
        url = None
        is_custom = False
        if custom:
            try:
                url = _public_url(custom['key'], custom['updated_at'])
                is_custom = True
            except Exception:
                logger.exception('Unable to build logo URL for report %s slot %s.', report_id, slot)
                custom = None
        if not custom and default:
            url = static(default['path'])

        slots.append({
            'slot': slot,
            'url': url,
            'alt': default['alt'] if default else 'Additional logo',
            'css_class': default['css_class'] if default else '',
            'is_custom': is_custom,
            'has_default': default is not None,
        })
    return slots


def get_cover_logos(report_id):
    """Return the cover logos for a report: the 3 defaults plus any custom extras."""
    return [logo for logo in get_logo_slots(report_id) if logo['url']]


def save_logo(report_id, slot, uploaded_file):
    """Validate and store an uploaded logo, replacing any existing file for the slot."""
    if slot not in LOGO_SLOTS:
        raise ValidationError('Invalid logo slot.')
    if uploaded_file.size > MAX_LOGO_BYTES:
        raise ValidationError('Logo must be 2MB or smaller.')

    extension = os.path.splitext(uploaded_file.name)[1].lower().lstrip('.')
    if extension == 'jpeg':
        extension = 'jpg'
    if extension not in ALLOWED_EXTENSIONS:
        raise ValidationError('Logo must be a PNG or JPG image.')

    try:
        image = Image.open(uploaded_file)
        image_format = image.format
        image.verify()
    except (UnidentifiedImageError, OSError):
        raise ValidationError('The uploaded file is not a valid image.')
    finally:
        uploaded_file.seek(0)

    if image_format not in FORMAT_EXTENSIONS:
        raise ValidationError('Logo must be a PNG or JPG image.')
    extension = FORMAT_EXTENSIONS[image_format]

    try:
        objects = _slot_objects(report_id)
        key = _object_key(report_id, slot, extension)
        old_keys = [
            item['key'] for name, item in objects.items()
            if name == slot and item['key'] != key
        ]
        content = uploaded_file.read()
        _bucket().upload(
            key,
            content,
            {'content-type': CONTENT_TYPES[extension], 'upsert': 'true'},
        )
        for old_key in old_keys:
            try:
                _bucket().remove([old_key])
            except Exception:
                logger.exception('Unable to remove old logo object %s.', old_key)
    except ValidationError:
        raise
    except Exception as exc:
        logger.exception('Unable to upload logo for report %s slot %s.', report_id, slot)
        raise ValidationError('Logo could not be uploaded. Please try again.') from exc

    return key


def reset_logo(report_id, slot):
    """Remove a custom logo so the slot falls back to its default image."""
    if slot not in LOGO_SLOTS:
        raise ValidationError('Invalid logo slot.')

    try:
        objects = _slot_objects(report_id)
        keys = [item['key'] for name, item in objects.items() if name == slot]
        if keys:
            _bucket().remove(keys)
    except ValidationError:
        raise
    except Exception as exc:
        logger.exception('Unable to reset logo for report %s slot %s.', report_id, slot)
        raise ValidationError('Logo could not be removed. Please try again.') from exc

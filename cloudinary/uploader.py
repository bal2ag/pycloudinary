# Copyright Cloudinary
import json, re, sys
from os.path import getsize
import urllib3
import cloudinary
import socket
from cloudinary import utils
from cloudinary.api import Error
from cloudinary.compat import string_types
from urllib3.exceptions import HTTPError

try:  # Python 2.7+
    from collections import OrderedDict
except ImportError:
    from urllib3.packages.ordered_dict import OrderedDict

_http = urllib3.PoolManager()

def upload(file, **options):
    params = utils.build_upload_params(**options)
    return call_api("upload", params, file = file, **options)

def unsigned_upload(file, upload_preset, **options):
    return upload(file, upload_preset=upload_preset, unsigned=True, **options)

def upload_image(file, **options):
    result = upload(file, **options)
    return cloudinary.CloudinaryImage(result["public_id"], version=str(result["version"]),
        format=result.get("format"), metadata=result)

def upload_resource(file, **options):
    result = upload(file, **options)
    return cloudinary.CloudinaryResource(result["public_id"], version=str(result["version"]),
        format=result.get("format"), type=result["type"], resource_type=result["resource_type"], metadata=result)

def upload_large(file, **options):
    """ Upload large files. """
    upload_id = utils.random_public_id()
    with open(file, 'rb') as file_io:
        upload = None
        current_loc = 0
        chunk_size = options.get("chunk_size", 20000000)
        file_size = getsize(file)
        chunk = file_io.read(chunk_size)        
        while (chunk):
            # chunk_io = BytesIO(chunk)
            # chunk_io.name = basename(file)
            range = "bytes {0}-{1}/{2}".format(current_loc, current_loc + len(chunk) - 1, file_size)
            current_loc += len(chunk)
            
            upload = upload_large_part((file,chunk), http_headers={"Content-Range": range, "X-Unique-Upload-Id": upload_id}, **options)
            options["public_id"] = upload.get("public_id")
            chunk = file_io.read(chunk_size)
        return upload

def upload_large_part(file, **options):
    """ Upload large files. """
    params = utils.build_upload_params(**options)
    if 'resource_type' not in options: options['resource_type'] = "raw"
    return call_api("upload", params, file=file, **options)

def destroy(public_id, **options):
    params = {
        "timestamp": utils.now(),
        "type": options.get("type"),
        "invalidate": options.get("invalidate"),
        "public_id":    public_id
    }
    return call_api("destroy", params, **options)

def rename(from_public_id, to_public_id, **options):
    params = {
        "timestamp": utils.now(),
        "type": options.get("type"),
        "overwrite": options.get("overwrite"),
        "invalidate": options.get("invalidate"),
        "from_public_id": from_public_id,
        "to_public_id": to_public_id
    }
    return call_api("rename", params, **options)

def explicit(public_id, **options):
    params = utils.build_upload_params(**options)
    params["public_id"] = public_id
    return call_api("explicit", params, **options)

def create_archive(**options):
    params = utils.archive_params(**options)
    if options.get("target_format") is not None:
        params["target_format"] = options.get("target_format")
    return call_api("generate_archive", params, **options)

def create_zip(**options):
    return create_archive(target_format="zip", **options)

def generate_sprite(tag, **options):
     params = {
        "timestamp": utils.now(),
        "tag": tag,
        "async": options.get("async"),
        "notification_url": options.get("notification_url"),
        "transformation": utils.generate_transformation_string(fetch_format=options.get("format"), **options)[0]
        }
     return call_api("sprite", params, **options)

def multi(tag, **options):
     params = {
        "timestamp": utils.now(),
        "tag": tag,
        "format": options.get("format"),
        "async": options.get("async"),
        "notification_url": options.get("notification_url"),
        "transformation": utils.generate_transformation_string(**options)[0]
        }
     return call_api("multi", params, **options)

def explode(public_id, **options):
     params = {
        "timestamp": utils.now(),
        "public_id": public_id,
        "format": options.get("format"),
        "notification_url": options.get("notification_url"),
        "transformation": utils.generate_transformation_string(**options)[0]
        }
     return call_api("explode", params, **options)

# options may include 'exclusive' (boolean) which causes clearing this tag from all other resources
def add_tag(tag, public_ids = [], **options):
    exclusive = options.pop("exclusive", None)
    command = "set_exclusive" if exclusive else "add"
    return call_tags_api(tag, command, public_ids, **options)

def remove_tag(tag, public_ids = [], **options):
    return call_tags_api(tag, "remove", public_ids, **options)

def replace_tag(tag, public_ids = [], **options):
    return call_tags_api(tag, "replace", public_ids, **options)

def call_tags_api(tag, command, public_ids = [], **options):
    params = {
        "timestamp": utils.now(),
        "tag": tag,
        "public_ids": utils.build_array(public_ids),
        "command": command,
        "type": options.get("type")
    }
    return call_api("tags", params, **options)

TEXT_PARAMS = ["public_id", "font_family", "font_size", "font_color", "text_align", "font_weight", "font_style", "background", "opacity", "text_decoration"]

def text(text, **options):
    params = {"timestamp": utils.now(), "text": text}
    for key in TEXT_PARAMS:
        params[key] = options.get(key)
    return call_api("text", params, **options)

def call_api(action, params, http_headers={}, return_error=False, unsigned=False, file=None, timeout=None, **options):
    try:
        file_io = None
        if unsigned:
          params = utils.cleanup_params(params)
        else:
          params = utils.sign_request(params, options)

        param_list = OrderedDict()
        for k, v in params.items():
            if isinstance(v, list):
                for i in range(len(v)):
                  param_list["{0}[{1}]".format(k, i )]= v[i]
            elif v:
                param_list[k]= v

        api_url = utils.cloudinary_api_url(action, **options)

        if file:
            if not isinstance(file, string_types):
                param_list["file"]=( file)
            elif not re.match(r'ftp:|https?:|s3:|data:[^;]*;base64,([a-zA-Z0-9\/+\n=]+)$', file):
                file_io = open(file, "rb")
                param_list['file']= (file, file_io.read())
            else:
                param_list["file"]=(file)

        headers = {"User-Agent": cloudinary.get_user_agent()}
        headers.update(http_headers)

        kw = {}
        if timeout is not None:
            kw['timeout'] = timeout

        code = 200
        try:
            response = _http.request("POST", api_url, param_list, headers, **kw)
        except HTTPError as e:
            raise Error("Unexpected error - {0!r}".format(e))
        except socket.error as e:
            raise Error("Socket error: {0!r}".format(e))

        try:
            result = json.loads(response.data.decode('utf-8'))
        except Exception as e:
            # Error is parsing json
            raise Error("Error parsing server response (%d) - %s. Got - %s", response.status, response, e)

        if "error" in result:
            if not response.status in [200, 400, 401, 403, 404, 500]:
                code = response.status
            if return_error:
                    result["error"]["http_code"] = code
            else:
                raise Error(result["error"]["message"])

        return result
    finally:
        if file_io: file_io.close()    

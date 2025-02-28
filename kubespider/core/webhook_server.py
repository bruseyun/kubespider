import logging
import json

from functools import wraps
from flask import Flask, jsonify, request

from core import download_trigger
from core import period_server
import core.kubespider_controller as kc
import source_provider.provider as sp
from api import types
from utils import global_config, helper


kubespider_server = Flask(__name__)

def auth_required(func):
    @wraps(func)
    def decorated(*args, **kwargs):
        if not check_auth(request.headers):
            return not_authenticated()
        return func(*args, **kwargs)
    return decorated

@kubespider_server.route('/healthz', methods=['GET'])
def health_check_handler():
    resp = jsonify('OK')
    resp.status_code = 200
    return resp

@kubespider_server.route('/api/v1/downloadproviders', methods=['GET'])
@auth_required
def list_download_provider_handler():
    download_providers = kc.kubespider_controller.download_providers

    resp_array = {}
    for i in download_providers:
        resp_array[i.get_provider_name()] = i.provider_enabled()
    resp = jsonify(resp_array)
    resp.content_type = "application/json"
    return resp

@kubespider_server.route('/api/v1/sourceproviders', methods=['GET'])
@auth_required
def list_source_provider_handler():
    source_providers = kc.kubespider_controller.source_providers

    resp_array = {}
    for i in source_providers:
        resp_array[i.get_provider_name()] = i.provider_enabled()
    resp = jsonify(resp_array)
    resp.content_type = "application/json"
    return resp

@kubespider_server.route('/api/v1/ptproviders', methods=['GET'])
@auth_required
def list_pt_provider_handler():
    pt_providers = kc.kubespider_controller.pt_providers

    resp_array = {}
    for i in pt_providers:
        resp_array[i.get_provider_name()] = i.provider_enabled()
    resp = jsonify(resp_array)
    resp.content_type = "application/json"
    return resp

@kubespider_server.route('/api/v1/download', methods=['POST'])
@auth_required
def download_handler():
    data = json.loads(request.data.decode("utf-8"))
    source = data['dataSource']
    path = ''
    if 'path' in data.keys():
        path = data['path']
    logging.info('Get webhook trigger:%s', source)

    match_one_provider = False
    match_provider = None
    for provider in kc.kubespider_controller.enabled_source_providers:
        if provider.is_webhook_enable() and provider.should_handle(source):
            match_provider = provider
            # Do not break here, in order to check whether it matchs multiple provider
            match_one_provider = True

    err = None
    if match_one_provider is False:
        contoller = helper.get_request_controller()
        link_type = helper.get_link_type(source, contoller)
        # If we not match the source provider, just download to common path
        # TODO: implement a better classification if no source provider match
        path = helper.convert_file_type_to_path(types.FILE_TYPE_COMMON) + '/' + path
        err = download_trigger.kubespider_downloader.download_file(source, path, link_type)

    if match_one_provider is True:
        if match_provider.get_provider_listen_type() == types.SOURCE_PROVIDER_DISPOSABLE_TYPE:
            err = download_links_with_provider(source, match_provider)
        else:
            match_provider.update_config(source)
            period_server.kubespider_period_server.trigger_run()

    if err is None:
        return send_ok_response()
    return send_bad_response(err)

@kubespider_server.route('/api/v1/refresh', methods=['GET'])
@auth_required
def refresh_handler():
    period_server.kubespider_period_server.trigger_run()
    return send_ok_response()

def download_links_with_provider(source: str, source_provider: sp.SourceProvider):
    link_type = source_provider.get_link_type()
    links = source_provider.get_links(source)
    for download_link in links:
        # The path rule should be like: {file_type}/{file_title}
        download_final_path = helper.convert_file_type_to_path(download_link['file_type']) + '/' + download_link['path']
        err = download_trigger.kubespider_downloader.\
            download_file(download_link['link'], \
                          download_final_path, link_type,\
                          source_provider)
        if err is not None:
            return err
    return None

def send_ok_response():
    resp = jsonify('OK')
    resp.status_code = 200
    resp.content_type = 'application/text'
    return resp

def send_bad_response(err):
    resp = jsonify(str(err))
    resp.status_code = 500
    resp.content_type = 'application/text'
    return resp

def check_auth(headers):
    auth_token = global_config.get_auth_token()
    if auth_token is None:
        return True
    if headers is None:
        return False
    authorization = headers.get("Authorization")
    if not authorization:
        return False
    try:
        auth_type, auth_info = authorization.split(None, 1)
        auth_type = auth_type.lower()
    except ValueError:
        return False
    if auth_type == "bearer" and auth_info == auth_token:
        return True
    return False

def not_authenticated():
    resp = jsonify('Auth Required')
    resp.status_code = 401
    resp.content_type = 'application/text'
    return resp

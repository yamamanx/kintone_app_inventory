import traceback
import logging.config
import os
import requests
import json
import config
from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities
from bs4 import BeautifulSoup


logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

domain = os.environ.get('KINTONE_DOMAIN', config.domain)
app = os.environ.get('KINTONE_APP', config.app)
api_key = os.environ.get('KINTONE_API_KEY', config.api_key)
admin = os.environ.get('KINTONE_ADMIN', config.admin)
password = os.environ.get('KINTONE_PASSWORD', config.password)

kintone_url = 'https://{domain}/k/v1/record.json'.format(
    domain=domain
)
kintone_headers = {
    'X-Cybozu-API-Token': api_key,
    'Content-Type': 'application/json'
}


def none_check(value):
    if value is None:
        return None
    elif value == '':
        return None
    else:
        return value


def get_app_info(html):

    app_info_array = []

    trs = html.findAll('tr', class_='gaia-admin-app-row')
    for tr in trs:
        tds = tr.findAll('td')
        if len(tds) <= 10:
            continue

        app_info = {
            'id': none_check(tds[0].get_text().strip()),
            'name': none_check(tds[1].get_text().strip()),
            'group': none_check(tds[3].get_text().strip()),
            'status': none_check(tds[4].get_text().strip()),
            'record_count': none_check(tds[5].get_text().strip()),
            'field_count': none_check(tds[6].get_text().strip()),
            'api_requests': none_check(tds[7].get_text().strip()),
            'customize': none_check(tds[8].get_text().strip()),
            'update_user': none_check(tds[9].get_text().strip()),
            'update_time': none_check(tds[10].get_text().strip())
        }
        logger.info(app_info)
        app_info_array.append(app_info)

    return app_info_array


def add_app_info(domain, page_count, browser, wait):
    if page_count == 0:
        pager = ''
    else:
        pager = str(page_count) + '/'

    app_manage_url = 'https://{domain}/k/admin/app/index#/{pager}sort/ID/order/ASC'.format(
        domain=domain,
        pager=pager
    )
    browser.get(app_manage_url)
    wait.until(ec.presence_of_all_elements_located)
    wait.until(ec.text_to_be_present_in_element(
        (By.CLASS_NAME, 'gaia-ui-pager-currentPage'),
        '{app_count} - '.format(
            app_count=str(page_count + 1)
        )
    ))
    logger.debug(browser.title)

    data = browser.page_source.encode('utf-8')
    html = BeautifulSoup(data, "html.parser")
    app_info = get_app_info(html)
    app_count = len(app_info)
    page_count += 20

    return {
        'app_info': app_info,
        'app_count': app_count,
        'page_count': page_count
    }


def is_exist(app_id):
    data = {
        'app': app,
        'query': 'id = "{app_id}"'.format(
            app_id=app_id
        ),
        'totalCount': 'true'
    }

    response = requests.get(
        'https://{domain}/k/v1/records.json'.format(
            domain=domain
        ),
        data=json.dumps(data),
        headers=kintone_headers
    )

    record_data = json.loads(response.text)
    total_count = int(record_data['totalCount'])

    if total_count > 0:
        return record_data['records'][0]['$id']['value']
    else:
        return False


def upsert_record(app_info):
    record = {}
    for key, value in app_info.items():
        record[key] = {
            'value': str(value)
        }

    record_id = is_exist(app_info['id'])
    if record_id:
        data = {
            'app': app,
            'id': record_id,
            'record': record
        }
        response = requests.put(
            kintone_url,
            data=json.dumps(data),
            headers=kintone_headers
        )

    else:
        data = {
            'app': app,
            'record': record
        }

        response = requests.post(
            kintone_url,
            data=json.dumps(data),
            headers=kintone_headers
        )

    logger.debug(response.text)


def main(event, context):
    try:
        user_agent = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/47.0.2526.111 Safari/537.36"
        )

        dcap = dict(DesiredCapabilities.PHANTOMJS)
        dcap["phantomjs.page.settings.userAgent"] = user_agent
        dcap["marionette"] = True
        dcap["phantomjs.page.settings.javascriptEnabled"] = True

        browser = webdriver.PhantomJS(
            service_log_path=os.path.devnull,
            executable_path="./phantomjs",
            service_args=['--ignore-ssl-errors=true', '--load-images=no', '--ssl-protocol=any'],
            desired_capabilities=dcap
        )

        wait = WebDriverWait(browser, 30)

        login_url = 'https://{domain}/login'.format(
            domain=domain
        )

        browser.get(login_url)

        xpath_user_id = '//*[@id="username-:0-text"]'
        xpath_password = '//*[@id="password-:1-text"]'
        xpath_button_login = '//*[@id="login-form-outer"]/form/div[4]/div[2]/input'

        wait.until(ec.visibility_of_element_located((By.XPATH, xpath_user_id)))
        wait.until(ec.visibility_of_element_located((By.XPATH, xpath_password)))
        wait.until(ec.visibility_of_element_located((By.XPATH, xpath_button_login)))

        user_id = browser.find_element_by_xpath(xpath_user_id)
        password_input = browser.find_element_by_xpath(xpath_password)
        btn_login = browser.find_element_by_xpath(xpath_button_login)

        user_id.send_keys(admin)
        password_input.send_keys(password)
        btn_login.click()

        wait.until(ec.visibility_of_element_located((By.ID, 'account-menu-cybozu')))
        logger.debug(browser.title)

        page_count = 0
        app_info_list = []

        result = add_app_info(domain, page_count, browser, wait)

        while result['app_count'] > 0:
            app_info_list.extend(result['app_info'])
            result = add_app_info(domain, result['page_count'], browser, wait)

        logger.info(app_info_list)

        for app_info in app_info_list:
            upsert_record(app_info)

    except Exception as e:
        logger.error(traceback.format_exc())
        raise Exception(traceback.format_exc())


def lambda_handler(event, context):
    try:
        event = main(event, context)
        return event
    except Exception as e:
        raise Exception(traceback.format_exc())


if __name__ == '__main__':
    logging.config.fileConfig("logging.conf")
    event = {}
    main(event, None)

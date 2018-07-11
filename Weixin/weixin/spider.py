from requests import Session
from weixin.config import *
from weixin.db import RedisQueue
from weixin.mysql import MySQL
from weixin.request import WeixinRequest
from urllib.parse import urlencode
import requests
from pyquery import PyQuery as pq
from requests import ReadTimeout, ConnectionError
import requests
import re

class Spider():
    base_url = 'http://weixin.sogou.com/weixin'
    keyword = '吃鸡'
    headers = {
    'Accept':'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
    'Accept-Language':'zh-CN,zh;q=0.9',
    'Connection':'keep-alive',
    'Cookie':'ABTEST=0|1531205382|v1; IPLOC=CN1100; SUID=4DFF7B7B2930990A000000005B445706; SUID=4DFF7B7B6119940A000000005B445706; weixinIndexVisited=1; SUV=000927B97B7BFF4D5B445710B98DF777; sct=1; SNUID=E250D5D4AEAADE3039217104AF02D5BA; JSESSIONID=aaaYi9nbXUS5thab6Mgrw',
    'Host':'weixin.sogou.com',
    'Upgrade-Insecure-Requests':'1',
    'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/62.0.3202.89 Safari/537.36'
}
    session = Session()
    queue = RedisQueue()
    mysql = MySQL()
    
    def get_proxy(self):
        """
        从代理池获取代理
        :return:
        """
        try:
            response = requests.get(PROXY_POOL_URL)
            if response.status_code == 200:
                print('Get Proxy', response.text)
                return response.text
            return None
        except requests.ConnectionError:
            return None
    
    def start(self):
        """
        初始化工作
        """
        # 全局更新Headers
        self.session.headers.update(self.headers)
        start_url = self.base_url + '?' + urlencode({'query': self.keyword, 'type': 2})
        weixin_request = WeixinRequest(url=start_url, callback=self.parse_index, need_proxy=False,timeout=15)
        # 调度第一个请求
        self.queue.add(weixin_request)
    
    def parse_index(self, response):
        """
        解析索引页
        :param response: 响应
        :return: 新的响应
        """
        doc = pq(response.text)
        items = doc('.news-box .news-list li .txt-box h3 a').items()
        for item in items:
            url = item.attr('href')
            weixin_request = WeixinRequest(url=url, callback=self.parse_detail)
            yield weixin_request
        next = doc('#sogou_next').attr('href')
        if next:
            url = self.base_url + str(next)
            weixin_request = WeixinRequest(url=url, callback=self.parse_index, need_proxy=False)
            yield weixin_request
    
    def parse_detail(self, response):
        """
        解析详情页
        :param response: 响应
        :return: 微信公众号文章
        """
        doc = pq(response.text)
        date = re.findall('publish_time = "(.*?)"', response.text, re.S)
        if date:
            data={
                'title': doc('.rich_media_title').text(),
                'content': doc('.rich_media_content').text(),
                # 'date': doc('#publish_time').text(),
                'date': date[0],
                'nickname': doc('#js_profile_qrcode > div > strong').text(),
                'wechat': doc('#js_profile_qrcode > div > p:nth-child(3) > span').text()
            }
            yield data
        else:
            data = {
                'title': doc('.rich_media_title').text(),
                'content': doc('.rich_media_content').text(),
                'date': doc('#publish_time').text(),
                # 'date': re.findall('publish_time = "(.*?)"', response.text, re.S)[0],
                'nickname': doc('#js_profile_qrcode > div > strong').text(),
                'wechat': doc('#js_profile_qrcode > div > p:nth-child(3) > span').text()
            }
            print(data)

    
    def request(self, weixin_request):
        """
        执行请求
        :param weixin_request: 请求
        :return: 响应
        """
        try:
            if weixin_request.need_proxy:
                proxy = self.get_proxy()
                if proxy:
                    proxies = {
                        'http': 'http://' + proxy,
                        'https': 'https://' + proxy
                    }
                    return self.session.send(weixin_request.prepare(),
                                             timeout=weixin_request.timeout, allow_redirects=False,)#proxies=proxies
            return self.session.send(weixin_request.prepare(), timeout=weixin_request.timeout, allow_redirects=False)
        except (ConnectionError, ReadTimeout) as e:
            print(e.args)
            return False
    
    def error(self, weixin_request):
        """
        错误处理
        :param weixin_request: 请求
        :return:
        """
        weixin_request.fail_time = weixin_request.fail_time + 1
        print('Request Failed', weixin_request.fail_time, 'Times', weixin_request.url)
        if weixin_request.fail_time < MAX_FAILED_TIME:
            self.queue.add(weixin_request)
    
    def schedule(self):
        """
        调度请求
        :return:
        """
        while not self.queue.empty():
            weixin_request = self.queue.pop()
            callback = weixin_request.callback
            print('Schedule', weixin_request.url)
            # response = self.request(weixin_request,allow_redirects=True)####
            response = requests.get(url=weixin_request.url,timeout=50)
            if response and response.status_code in VALID_STATUSES:
                results = list(callback(response))
                if results:
                    for result in results:
                        print('New Result', type(result))
                        if isinstance(result, WeixinRequest):
                            self.queue.add(result)
                        if isinstance(result, dict):
                            self.mysql.insert('articles', result)
                else:
                    self.error(weixin_request)
            else:
                self.error(weixin_request)
    
    def run(self):
        """
        入口
        :return:
        """
        self.start()
        self.schedule()


# if __name__ == '__main__':
#     spider = Spider()
#     spider.run()

#!/usr/bin/env python
"""
The MIT License (MIT)
=====================

Copyright © 2019 Ivan Stepanov <ivanstepanovftw@gmail.com>

Permission is hereby granted, free of charge, to any person
obtaining a copy of this software and associated documentation
files (the “Software”), to deal in the Software without
restriction, including without limitation the rights to use,
copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the
Software is furnished to do so, subject to the following
conditions:

The above copyright notice and this permission notice shall be
included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES
OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
OTHER DEALINGS IN THE SOFTWARE.
"""

import re
from html.parser import HTMLParser
from html.entities import name2codepoint
from time import sleep

import requests
import urllib
from typing import List


DEBUG_LurkLinksParser = False
DEBUG_links_copypasta = False

TARGET_LINKS = ["http://lurkmore.to/Категория:Копипаста:Архив", "http://lurkmore.to/index.php?title=Категория:Копипаста:Архив&pagefrom=Памятка+пассажира"]
LINK_BLACKLIST = [
    # "http://lurkmore.to/Копипаста:Музыкальная",
    # "http://lurkmore.to/%D0%9A%D0%BE%D0%BF%D0%B8%D0%BF%D0%B0%D1%81%D1%82%D0%B0:%D0%92_%D0%91%D0%B0%D0%BD%D0%BA%D0%B0%D1%85_%D1%80%D0%B0%D0%B1%D0%BE%D1%82%D0%B0%D1%8E%D1%82_%C2%AB%D0%B7%D0%BE%D0%BC%D0%B1%D0%B8%C2%BB",
]
RETRIES = [1, 2, 7, 21]  # сколько будем спать в секундах, если не можем получить ссыл очку


class LurkLinksParser(HTMLParser):
    def __init__(self):
        HTMLParser.__init__(self)
        # self.buf: List[str] = []
        # self.recording_div = 0
        # self.recording_p = 0

        # super().__init__(convert_charrefs=convert_charrefs)
        self.links: List[str] = []

    def handle_starttag(self, tag, attrs):
        # Only parse the 'anchor' tag.
        if tag == "a":
            # Check the list of defined attributes.
            for name, value in attrs:
                # If href is defined, print it.
                if name == "href":
                    DEBUG_LurkLinksParser and print("[DEBUG_LurkLinksParser]", urllib.parse.unquote(value))
                    self.links.append(value)


class LurkTextParser(HTMLParser):
    """
    Я паршу все <p>...</p>, которые находятся в <div id="mw-content-text">...</div>
    """
    def __init__(self):
        HTMLParser.__init__(self)
        self.buf: List[str] = []
        self.recording_div = 0
        self.recording_span = 0
        self.recording_contents_table = 0
        self.recording_non_printable = 0

    def is_allowed(self):
        return self.recording_div and not self.recording_span and not self.recording_contents_table and not self.recording_non_printable

    def handle_starttag(self, tag, attrs):
        if tag == 'div':
            if self.recording_div:
                self.recording_div += 1
                return
            for name, value in attrs:
                if name == 'id' and 'mw-content-text' in value:
                    self.recording_div = 1
        elif tag == 'span':
            if self.recording_span:
                self.recording_span += 1
                return
            for name, value in attrs:
                # всегда огораживается от грязного быдла,
                if name == 'class' and value in ('editsection', 'mw-headline'):
                    self.recording_span = 1
        elif tag == 'table':
            if self.recording_contents_table:
                self.recording_contents_table += 1
                return
            for name, value in attrs:
                if name == 'id' and value == 'toc':
                    self.recording_contents_table = 1
        elif tag in ('script', 'style'):
            if self.recording_non_printable:
                self.recording_non_printable += 1
                return
            self.recording_non_printable = 1
        elif tag in ('br', ) and self.is_allowed():
            self.buf.append('\n')
        # elif tag in ('p', 'li', 'br') and self.is_allowed():
        #     print("tag: ", tag)
        #     self.buf.append('\n')

    def handle_endtag(self, tag):
        if tag == 'div' and self.recording_div:
            self.recording_div -= 1
        elif tag == 'span' and self.recording_span:
            self.recording_span -= 1
        elif tag == 'table' and self.recording_contents_table:
            self.recording_contents_table -= 1
        elif tag in ('script', 'style') and self.recording_non_printable:
            self.recording_non_printable -= 1
        elif tag in ('p', 'li') and self.is_allowed():
            self.buf.append('\n')

    def handle_startendtag(self, tag, attrs):
        pass

    def handle_data(self, text):
        # print(self.recording_div, self.recording_span, self.recording_contents_table, self.recording_non_printable, "a: " + text)
        if self.is_allowed():
            a = re.sub(r"^[\s]*", "", text)
            a = re.sub(r"[\s]+$", "", a)
            if a:
                self.buf.append(a)

    def handle_entityref(self, name):
        if name in name2codepoint and not self.recording_contents_table:
            c = chr(name2codepoint[name])
            self.buf.append(c)

    def handle_charref(self, name):
        if not self.recording_contents_table:
            n = int(name[1:], 16) if name.startswith('x') else int(name)
            self.buf.append(chr(n))

    def data(self):
        return self.buf


def find_links(link):
    # Качаем страницу со ссылками
    r = requests.get(link)
    r.raise_for_status()

    # Находим все ссылки
    links_copypasta: List[str] = []

    lp = LurkLinksParser()
    lp.feed(r.content.decode("utf8"))
    for link in lp.links:
        if link.startswith(urllib.parse.quote("/Копипаста")):
            DEBUG_links_copypasta and print("[DEBUG_links_copypasta]", "http://lurkmore.to"+link)
            links_copypasta.append("http://lurkmore.to"+link)

    return links_copypasta


def main_loop(link) -> List[str]:
    copypastas: List[str] = []  # Тут будут все <p>...</p>, которые находятся в <div id="mw-content-text">...</div>
    # ["...", "..."]

    r = requests.get(link)
    r.raise_for_status()

    # with open("copypastas_1.html", "w") as fs:
    #     fs.writelines(r.content.decode("utf8"))
    ltp = LurkTextParser()
    ltp.feed(r.content.decode("utf8"))
    copypastas += ltp.data()
    return copypastas


def main():
    copypastas_links: List[str] = []  # Тут будут ссылки на копипасты

    # Собираем ссылки со страницы
    for link in TARGET_LINKS:
        link_human = urllib.parse.unquote(link)  # human readable link
        print("Processing page with target links:", link_human)

        for retry in range(len(RETRIES) + 1):
            try:
                links = find_links(link)
                print("    there are "+str(len(links))+" links")
                copypastas_links += links
                break
            except KeyboardInterrupt:
                print("KeyboardInterrupt! ["+str(retry+1)+"/"+str(len(RETRIES))+"]")
            except requests.HTTPError as e:
                print("Cannot parse page for links! ["+str(retry+1)+"/"+str(len(RETRIES))+"]")
                if retry == len(RETRIES):
                    raise
                sleep(RETRIES[retry])

    # print("There are "+str(len(copypastas_links))+" links:")
    # for link in copypastas_links:
    #     link_human = urllib.parse.unquote(link)  # human readable link
    #     print(link_human)

    # limit_links = -1  # лимит на скачивание, -1 для выключения лимита
    limit_links = 1

    # Парсим текст из каждой ссылки, записываем сразу шоб памяти меньше использовалось, мало ли гигабайты текста будут
    with open("copypastas.txt", "w") as f:
        for i in range(len(copypastas_links)):
            if limit_links == 0:
                break
            limit_links -= 1

            link = copypastas_links[i]
            link_human = urllib.parse.unquote(link)  # human readable link
            print("Processing page "+str(i+1)+"/"+str(len(copypastas_links))+": "+link_human)

            if link in LINK_BLACKLIST or link_human in LINK_BLACKLIST:
                print("Page is blacklisted:", link_human)
                continue

            for retry in range(len(RETRIES) + 1):
                try:
                    copypastas = main_loop(link)
                    for cp in copypastas:
                        # Вот тут можно каждый параграф пропарсить перед добавлением (либо не добавлять)
                        a = re.sub(r"[ \t]+", " ", cp)
                        a = re.sub(r"[—–]", "-", a)
                        a = re.sub(r"-+", "-", a)
                        f.write(a)
                    break
                except KeyboardInterrupt:
                    print("KeyboardInterrupt! ["+str(retry+1)+"/"+str(len(RETRIES))+"]")
                except requests.HTTPError as e:
                    if e.response == 404:
                        print("Cannot parse page! Not Found '"+str(link)+"', status_code: "+str(e.response))
                        break

                    print("Cannot parse page! ["+str(retry+1)+"/"+str(len(RETRIES))+"], status_code: "+str(e.response))
                    if retry == len(RETRIES):
                        raise
                    sleep(RETRIES[retry])


def debug():
    ltp = LurkTextParser()
    string = "".join(open("copypastas_1.html").readlines())
    ltp.feed(string)
    copypastas = ltp.data()

    for cp in copypastas:
        # Вот тут можно каждый параграф пропарсить перед добавлением (либо не добавлять)
        a = re.sub(r"[ \t]+", " ", cp)
        a = re.sub(r"[—–]", "-", a)
        a = re.sub(r"-+", "-", a)
        print(a, end="")


if __name__ == '__main__':
    main()
    # debug()

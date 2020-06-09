import json
import re
from datetime import datetime
from functools import lru_cache
from time import sleep
from urllib.parse import urljoin

from dateutil.relativedelta import *
from furl import furl
import xxhash
from bs4 import BeautifulSoup
from dateutil.parser import *
from requests_html import HTMLSession
from pathlib import Path


def dates(start, end):
    """
    generates all dates between start and end
    """
    now = datetime.now()
    for y in range(2016, now.year + 1):
        for m in range(1, 13):
            if y == now.year and m > now.month:
                continue
            r = int('{}{:02d}'.format(y, m))

            if r >= start and r <= end:
                yield '{}-{:02d}'.format(y, m)


@lru_cache(maxsize=999)
def extract_date_from_url(url):
    """
    >>> extract_date_from_url("https://billwurtz.com/questions/questions-2016-05.html")
    201605
    """
    try:
        date = int(''.join(str(furl(url)).split('/')[-1].split('-', 1)[-1].split('.')[0].split('-')))
    except:
        date = datetime.now().strftime('%Y%m')

    return date


def all_urls():
    all_urls = ['https://billwurtz.com/questions/questions.html']

    month = datetime.now()
    month += relativedelta(months=-1)
    last_month = int(month.strftime('%Y%m'))
    for d in reversed(list(dates(201605, last_month))):
        all_urls.append(f'https://billwurtz.com/questions/questions-{d}.html')

    return all_urls


def get_page(session, url):
    date = extract_date_from_url(url)
    p = Path(f'raw/{date}.html')

    if date != datetime.now().strftime('%Y%m') and p.is_file():
        return p.open().read()

    print(f'{datetime.now().isoformat()[:-7]} - 👾 downloading {url}')

    sleep(5)
    response = session.get(url)
    raw = response.text

    p.open(mode='w').write(raw)

    return raw


def get_lines(session, url):
    raw = get_page(session, url)

    date = int(extract_date_from_url(url))

    if date >= 201704:

        line = ''
        for x in raw.splitlines():

            x = x.replace('&nbsp;', ' ')
            x = x.replace('</br>', '')

            # skip empty lines
            if len(x.strip()) < 1:
                continue

            # a new item starts
            if x[:10] == '<h3> <dco>':
                if line[:6] == '<item>':
                    line += '</item>'

                    if '<remqq' in line:
                        s = r"</h3>(.+?)<remqq"
                        r = r"</h3><ans>\1</ans><remqq"
                        line = re.sub(s, r, line)
                    elif line.count('<qco>') > 1:
                        s = r"</h3>(.+?)<" # <-- Works, kindof
                        r = r"</h3><ans>\1</ans><"
                        line = re.sub(s, r, line)
                    else:
                        s = r"</h3>(.+?)</item"
                        # s = r"</h3>(.+?)<" # <-- Works, kindof
                        # s = r"</h3>(.+?)<[^(a)(/a)]"
                        r = r"</h3><ans>\1</ans><"
                        line = re.sub(s, r, line)

                    line = line.replace('<h3>', '')
                    line = line.replace('</h3>', '')

                    yield line

                line = '<item>'
                line += x

            else:
                line += x
    else:
        page = raw.replace('</br>', '\n')
        page = page.replace('<h3>', '\n<h3>')
        page = page.replace('&nbsp;', ' ')
        line = '<item>'
        for x in page.splitlines():
            if len(x) == 0:
                continue

            # a new item starts
            if x.startswith('<h3> <font color=#E9EC54>'):
                s = r"</h3>(.+?)<h3>"
                r = r"<ans>\1</ans>"
                line = re.sub(s, r, line)

                s = r"<h3> <font color=#E9EC54>(.+?)</font>"
                r = r"<dco>\1</dco>"
                line = re.sub(s, r, line)

                s = r"<font color=#B387FF>(.+?)</font>"
                r = r"<qco>\1</qco>"
                line = re.sub(s, r, line)

                s = r"</h3>(.+?)$"
                r = r"<ans>\1</ans>"
                line = re.sub(s, r, line)

                line += '</item>'

                yield line

                line = '<item>'

            line += x


def parse_item(line):
    soup = BeautifulSoup(line, 'html.parser')

    date_str = soup.find('dco')
    if date_str is None:
        return
    date_str = date_str.text

    # one broken date here: https://billwurtz.com/questions/questions-2016-05.html
    if 'apm' in date_str:
        date_str = date_str.replace('apm', 'pm ')
        with open("borken_lines.txt", "a+") as file:
            file.write(f'{line}\n')

    if date_str == '4.22.2011:07 am':
        date_str = '4.22.20 11:07 am'

    if '5.12.20' in date_str and '10:25 pm' in date_str:
        date_str = '5.12.20 10:25pm'

    date = parse(date_str)

    questions = soup.find_all('qco')
    answers = soup.find_all('ans')
    link = f'https://billwurtz.com/questions/q.php?date={date.strftime("%Y%m%d%H%M")}'
    item = {
        'd': date.isoformat(),
        'l': link,
        'q': [],
        # 'qs': len(questions),
        'h': xxhash.xxh64(line).hexdigest(),
    }
    for i in range(len(questions)):
        try:
            q = questions[i].__repr__()[6:-6].strip()
            a = answers[i].__repr__()[6:-6].strip()

            # absolutify links
            base_url = 'https://billwurtz.com/questions/'
            for l in answers[i].find_all('a'):
                absolute_link = urljoin(base_url, l.attrs['href'])
                l.attrs['href'] = absolute_link
                a = answers[i].__repr__()[6:-6].strip()

            for l in questions[i].find_all('a'):
                absolute_link = urljoin(base_url, l.attrs['href'])
                l.attrs['href'] = absolute_link
                q = questions[i].__repr__()[6:-6].strip()

            item['q'].append({
                'q': q,
                'a': a,
            })
        except:
            # print(f'💥\n{line}')
            with open("borken_lines.txt", "a+") as file:
                file.write(f'{line}\n')
    return item


if __name__ == '__main__':

    s = HTMLSession()

    all_items = []
    open('borken_lines.txt', 'w').close()

    for url in all_urls():
        date = extract_date_from_url(url)

        lines = list(get_lines(s, url))
        items = list(map(parse_item, lines))
        all_items.extend(items)
        all_items = list(filter(None, all_items))

        Path(f'ueqstions/json/{date}.json').write_text(json.dumps(items, indent=2, sort_keys=True, ensure_ascii=False))
        print(f'{datetime.now().isoformat()[:-7]} - 👌 {len(items)}/{len(all_items)} - {url}')

    Path(f'ueqstions.json').write_text(json.dumps(all_items))
    print(f'{datetime.now().isoformat()[:-7]} - 💾 saved file to disk')

# broken from 2017-03

"""
数据抓取脚本
抓取 GitHub Trending AI 项目 + 科技新闻
新闻源: Hacker News / TechCrunch / Ars Technica / The Verge
"""

import requests
from bs4 import BeautifulSoup
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime
import time


def fetch_github_trending():
    """抓取 GitHub Trending 页面"""
    url = "https://github.com/trending"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
    }

    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    return response.text


def parse_trending_data(html):
    """解析 Trending 页面，提取项目信息"""
    soup = BeautifulSoup(html, 'lxml')
    articles = soup.find_all('article', class_='Box-row')

    projects = []
    ai_keywords = [
        'ai', 'machine-learning', 'ml', 'deep-learning', 'neural',
        'gpt', 'llm', 'transformer', 'nlp', 'cv', 'computer-vision',
        'stable-diffusion', 'langchain', 'pytorch', 'tensorflow',
        'chatbot', 'openai', 'claude', 'gemini', 'embedding',
        'vector', 'rag', 'fine-tuning', 'agent', 'diffusion',
        'artificial-intelligence', 'keras', 'huggingface',
        'ollama', 'vllm', 'tgi', 'llama', 'mistral', 'gemma',
        'copilot', 'whisper', 'midjourney', 'dall-e', 'sd-webui',
        'comfyui', 'autogen', 'crewai', 'semantic', 'chromadb',
        'pinecone', 'weaviate', 'milvus', 'qdrant'
    ]

    for article in articles:
        try:
            # 项目名称
            repo_link = article.find('h2', class_='h3')
            if not repo_link:
                continue
            repo_link = repo_link.find('a')
            repo_path = repo_link.get('href', '').strip('/')

            owner, name = repo_path.split('/') if '/' in repo_path else ('', repo_path)

            # 描述
            desc_elem = article.find('p', class_='col-9')
            description = desc_elem.get_text(strip=True) if desc_elem else ''

            # Star 数量 - 找包含 "stargazer" 或 "star" 的链接
            star_elem = article.find('a', href=lambda h: h and '/stargazers' in h)
            if star_elem:
                stars = star_elem.get_text(strip=True).replace(',', '')
            else:
                star_elem = article.find('a', class_='Link--muted')
                stars = star_elem.get_text(strip=True).replace(',', '') if star_elem else '0'

            # 检查是否为 AI 相关
            repo_text = f"{name} {description} {repo_path}".lower()
            is_ai_related = any(keyword in repo_text for keyword in ai_keywords)

            # 今天 star 增长 - 在所有 d-inline-block span 中找包含 "star" 关键词的那个
            star_today = ''
            all_dinline_spans = article.find_all('span', class_='d-inline-block')
            for span in all_dinline_spans:
                text = span.get_text(strip=True)
                if re.search(r'\d+\s*stars?\s*(today|this\s*week)', text, re.IGNORECASE):
                    # 提取数字
                    match = re.search(r'([\d,]+)', text)
                    if match:
                        star_today = match.group(1).replace(',', '')
                    else:
                        star_today = text
                    break

            project = {
                'owner': owner,
                'name': name,
                'full_name': repo_path,
                'description': description,
                'stars': stars,
                'stars_today': star_today,
                'url': f'https://github.com/{repo_path}',
                'is_ai_related': is_ai_related
            }
            projects.append(project)

        except Exception as e:
            print(f"解析项目出错: {e}")
            continue

    return projects


def fetch_hacker_news():
    """抓取 Hacker News Top Stories（官方 Firebase API，极其稳定）"""
    news = []
    try:
        headers = {
            'User-Agent': 'AI-Daily-Trending-Bot/1.0'
        }
        # 获取 Top 30 个故事的 ID
        resp = requests.get(
            'https://hacker-news.firebaseio.com/v0/topstories.json',
            headers=headers, timeout=15
        )
        resp.raise_for_status()
        top_ids = resp.json()[:30]

        for i, story_id in enumerate(top_ids[:15], 1):
            try:
                item_resp = requests.get(
                    f'https://hacker-news.firebaseio.com/v0/item/{story_id}.json',
                    headers=headers, timeout=10
                )
                item_resp.raise_for_status()
                item = item_resp.json()
                if item and item.get('title') and item.get('url'):
                    score = item.get('score', 0)
                    news.append({
                        'rank': i,
                        'title': item['title'],
                        'url': item['url'],
                        'source': 'Hacker News',
                        'hot_value': str(score),
                        'is_hot': score >= 500 and i <= 3
                    })
            except Exception as e:
                print(f"  HN story {story_id} 获取失败: {e}")
                continue
    except Exception as e:
        print(f"抓取 Hacker News 失败: {e}")
    return news


def fetch_rss_feed(feed_url, source_name, max_items=10):
    """通用 RSS 抓取函数"""
    news = []
    try:
        headers = {
            'User-Agent': 'AI-Daily-Trending-Bot/1.0',
            'Accept': 'application/rss+xml, application/xml, text/xml, */*'
        }
        resp = requests.get(feed_url, headers=headers, timeout=15)
        resp.raise_for_status()

        root = ET.fromstring(resp.content)
        # 兼容 Atom 和 RSS 2.0
        if root.tag.endswith('}feed') or root.tag == 'feed':
            # Atom 格式
            entries = root.findall('.//{http://www.w3.org/2005/Atom}entry')
            if not entries:
                entries = root.findall('entry')
            for i, entry in enumerate(entries[:max_items], 1):
                title = (entry.find('{http://www.w3.org/2005/Atom}title') or entry.find('title'))
                link = None
                for link_elem in entry.findall('{http://www.w3.org/2005/Atom}link'):
                    if link_elem.get('rel', 'alternate') in ('alternate', '', None):
                        link = link_elem.get('href')
                        break
                if not link:
                    link_el = entry.find('{http://www.w3.org/2005/Atom}link') or entry.find('link')
                    link = link_el.get('href', '') if link_el is not None else ''

                if title is not None and title.text and link:
                    news.append({
                        'rank': i,
                        'title': title.text.strip(),
                        'url': link,
                        'source': source_name,
                        'hot_value': '',
                        'is_hot': False
                    })
        else:
            # RSS 2.0 格式
            items = root.findall('.//item')
            for i, item in enumerate(items[:max_items], 1):
                title = item.find('title')
                link = item.find('link')
                if title is not None and title.text:
                    news.append({
                        'rank': i,
                        'title': title.text.strip(),
                        'url': link.text.strip() if link is not None and link.text else '',
                        'source': source_name,
                        'hot_value': '',
                        'is_hot': False
                    })
    except Exception as e:
        print(f"抓取 {source_name} RSS 失败: {e}")
    return news


def save_data(projects, ai_projects, news_list):
    """保存数据到 JSON 文件"""
    today = datetime.now().strftime('%Y-%m-%d')

    ai_data = {
        'date': today,
        'updated_at': datetime.now().isoformat(),
        'count': len(ai_projects),
        'projects': ai_projects
    }

    all_data = {
        'date': today,
        'updated_at': datetime.now().isoformat(),
        'total_count': len(projects),
        'ai_count': len(ai_projects),
        'projects': projects
    }

    news_data = {
        'date': today,
        'updated_at': datetime.now().isoformat(),
        'count': len(news_list),
        'news': news_list
    }

    # 历史数据
    history_file = 'data/history.json'
    try:
        with open(history_file, 'r', encoding='utf-8') as f:
            history = json.load(f)
    except Exception:
        history = []

    today_exists = False
    for i, h in enumerate(history):
        if h['date'] == today:
            history[i]['ai_count'] = len(ai_projects)
            history[i]['news_count'] = len(news_list)
            history[i]['ai_projects'] = [{'name': p['full_name'], 'stars': p['stars'], 'url': p['url']} for p in ai_projects[:5]]
            history[i]['top_news'] = [{'title': n['title'][:30], 'source': n['source']} for n in news_list[:5]]
            today_exists = True
            break

    if not today_exists:
        history.append({
            'date': today,
            'ai_count': len(ai_projects),
            'news_count': len(news_list),
            'ai_projects': [{'name': p['full_name'], 'stars': p['stars'], 'url': p['url']} for p in ai_projects[:5]],
            'top_news': [{'title': n['title'][:30], 'source': n['source']} for n in news_list[:5]]
        })

    history = history[-30:]

    with open('data/daily.json', 'w', encoding='utf-8') as f:
        json.dump(ai_data, f, ensure_ascii=False, indent=2)

    with open('data/all.json', 'w', encoding='utf-8') as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2)

    with open('data/news.json', 'w', encoding='utf-8') as f:
        json.dump(news_data, f, ensure_ascii=False, indent=2)

    with open('data/history.json', 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

    print(f"数据已保存:")
    print(f"   - AI 项目: {len(ai_projects)} 个")
    print(f"   - 科技新闻: {len(news_list)} 条")


def main():
    print("开始抓取数据...")

    # 1. GitHub Trending
    print("抓取 GitHub Trending...")
    html = fetch_github_trending()
    projects = parse_trending_data(html)
    ai_projects = [p for p in projects if p['is_ai_related']]
    print(f"   - Trending: {len(projects)} 个项目, 其中 AI 相关: {len(ai_projects)} 个")

    # 2. 科技新闻
    print("抓取科技新闻...")
    all_news = []

    # Hacker News (官方 API, 最稳定)
    hn_news = fetch_hacker_news()
    all_news.extend(hn_news)
    print(f"   - Hacker News: {len(hn_news)} 条")

    time.sleep(0.5)

    # TechCrunch (RSS)
    tc_news = fetch_rss_feed('https://techcrunch.com/feed/', 'TechCrunch', 8)
    all_news.extend(tc_news)
    print(f"   - TechCrunch: {len(tc_news)} 条")

    time.sleep(0.3)

    # Ars Technica (RSS)
    at_news = fetch_rss_feed('https://feeds.arstechnica.com/arstechnica/index', 'Ars Technica', 8)
    all_news.extend(at_news)
    print(f"   - Ars Technica: {len(at_news)} 条")

    time.sleep(0.3)

    # The Verge (RSS)
    verge_news = fetch_rss_feed('https://www.theverge.com/rss/index.xml', 'The Verge', 8)
    all_news.extend(verge_news)
    print(f"   - The Verge: {len(verge_news)} 条")

    # 按排名排序，取前 20 条
    news_list = all_news[:20]

    # 更新排名
    for i, news in enumerate(news_list, 1):
        news['rank'] = i

    save_data(projects, ai_projects, news_list)
    print(f"抓取完成! AI 项目: {len(ai_projects)}/{len(projects)}, 新闻: {len(news_list)}")


if __name__ == '__main__':
    main()

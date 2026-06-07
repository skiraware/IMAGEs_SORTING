import urllib.request
import os
import ssl

# 如果遇到 SSL 证书问题（可选），取消下一行的注释
# ssl._create_default_https_context = ssl._create_unverified_context

print("Creating static folder...")
os.makedirs("static", exist_ok=True)

# 设置请求头，模拟 Chrome 浏览器
headers = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

def download_file(url, filepath):
    """带请求头的下载函数"""
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req) as response, open(filepath, 'wb') as out_file:
        out_file.write(response.read())
    print(f"  -> Saved to {filepath}")

# 依赖列表
urls = {
    "react.development.js": "https://unpkg.com/react@18/umd/react.development.js",
    "react-dom.development.js": "https://unpkg.com/react-dom@18/umd/react-dom.development.js",
    "babel.min.js": "https://unpkg.com/@babel/standalone/babel.min.js",
    "gsap.min.js": "https://cdnjs.cloudflare.com/ajax/libs/gsap/3.12.2/gsap.min.js",
    # 关键修改：使用 jsDelivr 提供的 Tailwind CSS 文件（稳定且允许程序下载）
"tailwind.css": "https://cdn.jsdelivr.net/npm/tailwindcss/dist/tailwind.min.css"
}

for filename, url in urls.items():
    print(f"Downloading {filename} from {url}...")
    try:
        download_file(url, os.path.join("static", filename))
    except Exception as e:
        print(f"❌ Failed to download {filename}: {e}")

print("\n✅ All dependencies downloaded! You can now run your app entirely offline.")
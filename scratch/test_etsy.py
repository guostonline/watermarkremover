import requests
from bs4 import BeautifulSoup

def test_scrape(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        print(f"Scraping {url}...")
        response = requests.get(url, headers=headers, timeout=10)
        print(f"Status: {response.status_code}")
        if response.status_code != 200:
            print(response.text[:200])
            return
            
        soup = BeautifulSoup(response.text, "html.parser")
        og_image = soup.find("meta", property="og:image")
        if og_image:
            print(f"Found og:image: {og_image.get('content')}")
        else:
            print("No og:image found")
            
        main_img = soup.find("img", {"class": "listing-main-image"})
        if main_img:
            print(f"Found main-image: {main_img.get('src')}")
        else:
            print("No main-image found")
            
    except Exception as e:
        print(f"Error: {str(e)}")

if __name__ == "__main__":
    test_scrape("https://www.etsy.com/listing/1698244464/summer-maxi-dress-sewing-pattern-pdf")

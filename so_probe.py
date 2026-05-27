import requests
import json

def search_stackoverflow(error_query):
    print(f"🔍 Searching StackOverflow for: '{error_query}'...")
    
    url = "https://api.stackexchange.com/2.3/search/advanced"
    
    params = {
        "order": "desc",
        "sort": "relevance",
        "q": error_query,
        "tagged": "c++",         
        "site": "stackoverflow",
        "filter": "withbody",    
        "pagesize": 1            
    }

    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        
        if data["items"]:
            top_thread = data["items"][0]
            print("\n✅ SUCCESS: Payload Secured.")
            print(f"Title: {top_thread['title']}")
            print(f"Link: {top_thread['link']}")
        else:
            print("❌ No results found.")
            
    except Exception as e:
        print(f"❌ API Failure: {e}")

if __name__ == "__main__":
    search_stackoverflow("std::string buffer overflow")
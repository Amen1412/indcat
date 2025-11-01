from flask import Flask, jsonify, request, render_template_string, redirect
from flask_cors import CORS
import requests
from datetime import datetime
import os
import base64
import json
import threading
import time

app = Flask(__name__)
CORS(app)

TMDB_BASE_URL = "https://api.themoviedb.org/3"

# Global movie cache per API key
movie_cache = {}
cache_lock = threading.Lock()

def fetch_and_cache_movies(api_key, language="ml"):
    """Fetch all Malayalam OTT movies from TMDB and cache them"""
    cache_key = f"{api_key}_{language}"

    print(f"[CACHE] Fetching {language.upper()} OTT movies...")
    today = datetime.now().strftime("%Y-%m-%d")
    final_movies = []

    for page in range(1, 1000):
        print(f"[INFO] Checking page {page}")
        params = {
            "api_key": api_key,
            "with_original_language": language,
            "sort_by": "release_date.desc",
            "release_date.lte": today,
            "region": "IN",
            "page": page
        }

        try:
            response = requests.get(f"{TMDB_BASE_URL}/discover/movie", params=params, timeout=10)
            if response.status_code != 200:
                print(f"[ERROR] API returned status {response.status_code}")
                break

            results = response.json().get("results", [])
            if not results:
                print(f"[INFO] No more results at page {page}")
                break

            for movie in results:
                movie_id = movie.get("id")
                title = movie.get("title")
                if not movie_id or not title:
                    continue

                # Check OTT availability
                try:
                    providers_url = f"{TMDB_BASE_URL}/movie/{movie_id}/watch/providers"
                    prov_response = requests.get(providers_url, params={"api_key": api_key}, timeout=10)
                    prov_data = prov_response.json()

                    # Check if available on any OTT platform in India
                    if "results" in prov_data and "IN" in prov_data["results"]:
                        if "flatrate" in prov_data["results"]["IN"]:
                            # Get IMDb ID
                            ext_url = f"{TMDB_BASE_URL}/movie/{movie_id}/external_ids"
                            ext_response = requests.get(ext_url, params={"api_key": api_key}, timeout=10)
                            ext_data = ext_response.json()
                            imdb_id = ext_data.get("imdb_id")

                            if imdb_id and imdb_id.startswith("tt"):
                                movie["imdb_id"] = imdb_id
                                final_movies.append(movie)
                except Exception as e:
                    print(f"[ERROR] Failed to check movie {movie_id}: {e}")
                    continue

        except Exception as e:
            print(f"[ERROR] Page {page} failed: {e}")
            break

    # Deduplicate by IMDb ID
    seen_ids = set()
    unique_movies = []
    for movie in final_movies:
        imdb_id = movie.get("imdb_id")
        if imdb_id and imdb_id not in seen_ids:
            seen_ids.add(imdb_id)
            unique_movies.append(movie)

    with cache_lock:
        movie_cache[cache_key] = unique_movies

    print(f"[CACHE] Fetched {len(unique_movies)} {language.upper()} OTT movies ✅")
    return unique_movies

def to_stremio_meta(movie):
    """Convert TMDB movie to Stremio meta format"""
    try:
        imdb_id = movie.get("imdb_id")
        title = movie.get("title")
        if not imdb_id or not title:
            return None

        return {
            "id": imdb_id,
            "type": "movie",
            "name": title,
            "poster": f"https://image.tmdb.org/t/p/w500{movie['poster_path']}" if movie.get("poster_path") else None,
            "description": movie.get("overview", ""),
            "releaseInfo": movie.get("release_date", ""),
            "background": f"https://image.tmdb.org/t/p/w780{movie['backdrop_path']}" if movie.get("backdrop_path") else None
        }
    except Exception as e:
        print(f"[ERROR] to_stremio_meta failed: {e}")
        return None

def decode_user_config(config_string):
    """Decode base64 user configuration from URL"""
    try:
        decoded = base64.b64decode(config_string).decode('utf-8')
        return json.loads(decoded)
    except:
        return None

def encode_user_config(config_dict):
    """Encode user configuration to base64 for URL"""
    json_str = json.dumps(config_dict)
    return base64.b64encode(json_str.encode('utf-8')).decode('utf-8')

# HTML Configuration Page
CONFIGURE_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>IndCat Configuration</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }

        .container {
            background: white;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            max-width: 500px;
            width: 100%;
            padding: 40px;
            animation: slideIn 0.5s ease-out;
        }

        @keyframes slideIn {
            from {
                opacity: 0;
                transform: translateY(-30px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }

        .logo {
            text-align: center;
            margin-bottom: 30px;
        }

        .logo h1 {
            color: #667eea;
            font-size: 2.5em;
            font-weight: bold;
            margin-bottom: 10px;
        }

        .logo p {
            color: #666;
            font-size: 0.95em;
        }

        .form-group {
            margin-bottom: 25px;
        }

        label {
            display: block;
            color: #333;
            font-weight: 600;
            margin-bottom: 8px;
            font-size: 0.95em;
        }

        input[type="text"] {
            width: 100%;
            padding: 12px 15px;
            border: 2px solid #e0e0e0;
            border-radius: 10px;
            font-size: 1em;
            transition: all 0.3s ease;
        }

        input[type="text"]:focus {
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
        }

        .help-text {
            font-size: 0.85em;
            color: #888;
            margin-top: 5px;
        }

        .help-text a {
            color: #667eea;
            text-decoration: none;
        }

        .help-text a:hover {
            text-decoration: underline;
        }

        .language-section {
            background: #f8f9fa;
            padding: 20px;
            border-radius: 10px;
            margin-bottom: 25px;
        }

        .language-section h3 {
            color: #333;
            font-size: 1.1em;
            margin-bottom: 15px;
        }

        .language-grid {
            display: grid;
            grid-template-columns: 1fr;
            gap: 10px;
        }

        .language-item {
            display: flex;
            align-items: center;
            padding: 12px;
            background: white;
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.3s ease;
            border: 2px solid transparent;
        }

        .language-item:hover {
            border-color: #667eea;
            transform: translateX(5px);
        }

        .language-item input[type="checkbox"] {
            width: 20px;
            height: 20px;
            margin-right: 12px;
            cursor: pointer;
            accent-color: #667eea;
        }

        .language-item label {
            margin: 0;
            cursor: pointer;
            flex-grow: 1;
            font-weight: 500;
        }

        .language-badge {
            background: #667eea;
            color: white;
            padding: 4px 10px;
            border-radius: 12px;
            font-size: 0.75em;
            font-weight: bold;
        }

        .submit-btn {
            width: 100%;
            padding: 15px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 10px;
            font-size: 1.1em;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
            box-shadow: 0 4px 15px rgba(102, 126, 234, 0.4);
        }

        .submit-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(102, 126, 234, 0.6);
        }

        .submit-btn:active {
            transform: translateY(0);
        }

        .error {
            background: #fee;
            color: #c33;
            padding: 12px;
            border-radius: 8px;
            margin-bottom: 20px;
            border-left: 4px solid #c33;
        }

        .note {
            background: #e3f2fd;
            color: #1565c0;
            padding: 15px;
            border-radius: 8px;
            margin-top: 20px;
            font-size: 0.9em;
            border-left: 4px solid #1565c0;
        }

        @media (max-width: 600px) {
            .container {
                padding: 30px 20px;
            }

            .logo h1 {
                font-size: 2em;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="logo">
            <h1>🎬 IndCat</h1>
            <p>Indian OTT Movies Catalog for Stremio</p>
        </div>

        <form method="POST" action="/configure">
            <div class="form-group">
                <label for="api_key">TMDB API Key *</label>
                <input type="text" id="api_key" name="api_key" required placeholder="Enter your TMDB API key">
                <p class="help-text">
                    Don't have one? <a href="https://www.themoviedb.org/settings/api" target="_blank">Get it here</a>
                </p>
            </div>

            <div class="language-section">
                <h3>Select Languages</h3>
                <div class="language-grid">
                    <div class="language-item">
                        <input type="checkbox" id="malayalam" name="languages" value="ml" checked>
                        <label for="malayalam">Malayalam</label>
                        <span class="language-badge">ACTIVE</span>
                    </div>
                </div>
            </div>

            <button type="submit" class="submit-btn">✨ Configure & Install</button>

            <div class="note">
                <strong>Note:</strong> More languages (Hindi, Tamil, Telugu, Kannada) coming soon! This addon only displays movie catalogs - it doesn't provide streaming links.
            </div>
        </form>
    </div>
</body>
</html>
"""

@app.route("/")
def home():
    """Redirect to configuration page"""
    return redirect("/configure")

@app.route("/configure")
def configure():
    """Serve configuration page"""
    return render_template_string(CONFIGURE_HTML)

@app.route("/configure", methods=["POST"])
def configure_post():
    """Process configuration form"""
    api_key = request.form.get("api_key", "").strip()
    languages = request.form.getlist("languages")

    if not api_key:
        return "API key is required", 400

    if not languages:
        languages = ["ml"]  # Default to Malayalam

    # Encode configuration
    config = {
        "api_key": api_key,
        "languages": languages
    }
    config_string = encode_user_config(config)

    # Redirect to manifest with encoded config
    base_url = request.host_url.rstrip("/")
    manifest_url = f"{base_url}/{config_string}/manifest.json"

    return redirect(manifest_url)

@app.route("/manifest.json")
def manifest_default():
    """Default manifest - redirects to configure"""
    return jsonify({
        "id": "org.indcat",
        "version": "1.0.0",
        "name": "IndCat",
        "description": "Please configure this addon with your TMDB API key",
        "resources": [],
        "types": [],
        "catalogs": [],
        "behaviorHints": {
            "configurable": True,
            "configurationRequired": True
        }
    })

@app.route("/<config_string>/manifest.json")
def manifest(config_string):
    """Manifest with user configuration"""
    config = decode_user_config(config_string)

    if not config or "api_key" not in config:
        return jsonify({"error": "Invalid configuration"}), 400

    languages = config.get("languages", ["ml"])

    # Build catalogs for selected languages
    language_names = {
        "ml": "Malayalam",
        "hi": "Hindi",
        "ta": "Tamil",
        "te": "Telugu",
        "kn": "Kannada"
    }

    catalogs = []
    for lang in languages:
        catalogs.append({
            "type": "movie",
            "id": lang,
            "name": language_names.get(lang, lang.upper()),
            "extra": [
                {"name": "skip", "isRequired": False}
            ]
        })

    return jsonify({
        "id": "org.indcat",
        "version": "1.0.0",
        "name": "IndCat",
        "description": "Indian OTT Movies Catalog",
        "resources": ["catalog"],
        "types": ["movie"],
        "catalogs": catalogs,
        "idPrefixes": ["tt"],
        "behaviorHints": {
            "configurable": True
        }
    })

@app.route("/<config_string>/catalog/movie/<language>.json")
def catalog(config_string, language):
    """Catalog endpoint with pagination support"""
    config = decode_user_config(config_string)

    if not config or "api_key" not in config:
        return jsonify({"metas": []}), 400

    api_key = config["api_key"]
    skip = int(request.args.get("skip", 0))

    cache_key = f"{api_key}_{language}"

    # Check if cache exists
    with cache_lock:
        if cache_key not in movie_cache:
            # Start background fetch if not already cached
            def fetch_in_background():
                fetch_and_cache_movies(api_key, language)

            threading.Thread(target=fetch_in_background, daemon=True).start()

            # Return empty for now, will be available on next request
            return jsonify({"metas": []})

        cached_movies = movie_cache[cache_key]

    # Paginate: return max 100 items
    end = skip + 100
    paginated_movies = cached_movies[skip:end]

    # Convert to Stremio format
    metas = [meta for meta in (to_stremio_meta(m) for m in paginated_movies) if meta]

    print(f"[CATALOG] Returning {len(metas)} movies (skip={skip}, total={len(cached_movies)})")

    return jsonify({"metas": metas})

@app.route("/<config_string>/refresh")
def refresh(config_string):
    """Manually refresh cache"""
    config = decode_user_config(config_string)

    if not config or "api_key" not in config:
        return jsonify({"error": "Invalid configuration"}), 400

    api_key = config["api_key"]
    languages = config.get("languages", ["ml"])

    def do_refresh():
        for lang in languages:
            try:
                fetch_and_cache_movies(api_key, lang)
                print(f"[REFRESH] {lang.upper()} complete ✅")
            except Exception as e:
                print(f"[REFRESH ERROR] {lang.upper()}: {e}")

    threading.Thread(target=do_refresh, daemon=True).start()

    return jsonify({"status": "refresh started in background"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    print(f"🚀 Starting IndCat Stremio Addon on 0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)

# API Endpoints

This document lists the HTTP endpoints provided by the Spacetime application.

| Path | Methods | Description |
|------|---------|-------------|
| `/` | `GET` | Home page listing posts or redirect to configured start page |
| `/admin/posts` | `GET` | List posts for administrators |
| `/admin/requested` | `GET, POST` | Manage user requested posts |
| `/citation/fetch` | `POST` | Fetch citation metadata by DOI |
| `/citation/suggest` | `POST` | Suggest citations for provided text |
| `/citation/suggest_line` | `POST` | Return citation suggestions for a single line of text |
| `/citations/stats` | `GET` | Summary statistics for citations |
| `/docs/<string:language>/<path:doc_path>` | `GET` | Retrieve a document by language and path |
| `/geocode` | `GET` | Geocode an address string |
| `/login` | `GET, POST` | Log in a user |
| `/logout` | `GET` | Log out current user |
| `/markdown/preview` | `POST` | Render Markdown preview |
| `/notifications` | `GET` | Display user notifications |
| `/og` | `GET` | Fetch Open Graph metadata for a URL |
| `/post/<int:post_id>` | `GET` | View an individual post |
| `/post/<int:post_id>/backlinks` | `GET` | Show posts linking to the given post |
| `/post/<int:post_id>/citation/<int:cid>/delete` | `POST` | Delete a citation from a post |
| `/post/<int:post_id>/citation/<int:cid>/edit` | `GET, POST` | Edit an existing citation |
| `/post/<int:post_id>/citation/new` | `POST` | Add a new citation to a post |
| `/post/<int:post_id>/delete` | `POST` | Delete the specified post |
| `/post/<int:post_id>/diff/<int:rev_id>` | `GET` | Show differences for a revision |
| `/post/<int:post_id>/edit` | `GET, POST` | Edit an existing post |
| `/post/<int:post_id>/history` | `GET` | View revision history for a post |
| `/post/<int:post_id>/revert/<int:rev_id>` | `POST` | Revert a post to a revision |
| `/post/<int:post_id>/unwatch` | `POST` | Stop watching a post |
| `/post/<int:post_id>/watch` | `POST` | Watch a post for changes |
| `/post/<string:language>/<path:doc_path>` | `GET` | View a post by language and path |
| `/post/new` | `GET, POST` | Create a new post |
| `/post/request` | `GET, POST` | Request that a post be created |
| `/posts` | `GET` | List all posts |
| `/posts/requested` | `GET` | List user requested posts |
| `/recent` | `GET` | Recent changes across posts |
| `/register` | `GET, POST` | Register a new user |
| `/rss.xml` | `GET` | RSS feed of recent posts |
| `/search` | `GET` | Search posts and metadata |
| `/settings` | `GET, POST` | Manage user settings |
| `/sitemap.xml` | `GET` | Generate a basic XML sitemap of all posts |
| `/tag/<string:name>` | `GET` | Filter posts by tag |
| `/tags` | `GET` | List all tags |
| `/user/<username>` | `GET, POST` | View or update a user profile |

## JSON API Examples

The following endpoints return JSON responses and can be used programmatically.

### `/markdown/preview` (`POST`)

Render a snippet of Markdown and return the HTML.

**Parameters**

- `text` (string, required) – Markdown source to render
- `language` (string, optional) – language code used for resolving wiki links

**Example**

Request

```http
POST /markdown/preview
Content-Type: application/json

{"text": "[[Page]]", "language": "es"}
```

Response

```json
{"html": "<p><a href=\"/docs/es/Page\">Page</a></p>"}
```

### `/og` (`GET`)

Fetch Open Graph metadata for a URL.

**Parameters**

- `url` (string, required) – absolute URL to inspect

**Example**

Request: `GET /og?url=https://example.com`

Response

```json
{"title": "Example Domain", "description": "...", "image": null}
```

### `/geocode` (`GET`)

Return coordinates for a human-readable address.

**Parameters**

- `address` (string, required) – address to geocode

**Example**

Request: `GET /geocode?address=1600+Pennsylvania+Ave+NW`

Response

```json
{"lat": 38.8977, "lon": -77.0365}
```

### `/citation/suggest` (`POST`)

Suggest citations for multiple sentences of text. Only the most frequent
keywords from each sentence are used when querying external services.

**Parameters**

- `text` (string, required) – body of text to analyse

**Example**

```http
POST /citation/suggest
Content-Type: application/json

{"text": "Albert Einstein was born in Ulm."}
```

Response

```json
{
  "results": {
    "Albert Einstein was born in Ulm.": [
      {"text": "@article{...}", "part": {"title": "...", "doi": "10.1000/xyz"}}
    ]
  }
}
```

### `/citation/suggest_line` (`POST`)

Like `/citation/suggest` but processes one line at a time, extracting the
most frequent words from that line to build the search query.

**Parameters**

- `line` (string, required) – single line of text

**Example**

```http
POST /citation/suggest_line
Content-Type: application/json

{"line": "Quantum mechanics revolutionised physics."}
```

Response

```json
{
  "results": {
    "Quantum mechanics revolutionised physics.": [
      {"text": "@article{...}", "part": {"title": "...", "doi": "10.1000/abc"}}
    ]
  }
}
```

### `/citation/fetch` (`POST`)

Fetch metadata for the first citation that matches a title.

**Parameters**

- `title` (string, required) – work title used to query Crossref

**Example**

```http
POST /citation/fetch
Content-Type: application/json

{"title": "The Meaning of Relativity"}
```

Response

```json
{
  "part": {"title": "The Meaning of Relativity", "doi": "10.1000/rel"},
  "text": "@book{...}"
}
```

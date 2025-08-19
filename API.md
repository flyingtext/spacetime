# API Endpoints

This document lists the HTTP endpoints provided by the Spacetime application.

| Path | Methods | Description |
|------|---------|-------------|
| `/` | `GET` | Home page listing posts or redirect to configured start page |
| `/admin/posts` | `GET` | List posts for administrators |
| `/admin/requested` | `GET, POST` | Manage user requested posts |
| `/admin/db-status` | `GET` | View database status and performance statistics for administrators |
| `/citation/fetch` | `POST` | Fetch citation metadata by DOI |
| `/citation/suggest` | `POST` | Suggest citations for provided text |
| `/citation/suggest_line` | `POST` | Return citation suggestions for a single line of text |
| `/citations/stats` | `GET` | Summary statistics for citations |
| `/<string:language>/<path:doc_path>` | `GET` | Retrieve a document by language and path |
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
| `/api/posts/<int:post_id>/citation` | `POST` | Add a citation to a post via URL |
| `/post/<int:post_id>/delete` | `POST` | Delete the specified post |
| `/post/<int:post_id>/diff/<int:rev_id>` | `GET` | Show differences for a revision |
| `/post/<int:post_id>/edit` | `GET, POST` | Edit an existing post |
| `/post/<int:post_id>/history` | `GET` | View revision history for a post |
| `/post/<int:post_id>/revert/<int:rev_id>` | `POST` | Revert a post to a revision |
| `/post/<int:post_id>/unwatch` | `POST` | Stop watching a post |
| `/post/<int:post_id>/watch` | `POST` | Watch a post for changes |
| `/post/<string:language>/<path:doc_path>` | `GET` | View a post by language and path |
| `/post/new` | `GET, POST` | Create a new post |
| `/api/posts` | `GET` | Search posts with optional pagination |
| `/api/posts` | `POST` | Create a new post via JSON (supports location) |
| `/api/posts/<int:post_id>` | `GET` | Read post content and metadata |
| `/api/posts/<int:post_id>` | `PUT` | Update post content and metadata |
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

## Endpoint Details

### `/posts` (`GET`)
List all published posts. Optional query parameter `tag` filters by tag name.

### `/` (`GET`)
Home page listing posts or redirecting to the configured start page.

### `/rss.xml` (`GET`)
Return an RSS feed of recent posts.

### `/sitemap.xml` (`GET`)
Generate an XML sitemap of all posts.

### `/recent` (`GET`)
Display the twenty most recent revisions.

### `/register` (`GET, POST`)
Register a new user. The POST body must include `username` and `password` fields.

### `/login` (`GET, POST`)
Authenticate an existing user with `username` and `password` fields.

### `/logout` (`GET`)
Log out the current user.

### `/user/<username>` (`GET, POST`)
View a user profile or update your own bio via the `bio` form field.

### `/notifications` (`GET`)
List notifications for the authenticated user.

### `/post/request` (`GET, POST`)
Submit a request for a new post. Requires `title` and `description` fields on POST.

### `/posts/requested` (`GET`)
Show all user requested posts.

### `/admin/requested` (`GET, POST`)
Admins can view and comment on requested posts. POST accepts `request_id` and `comment`.

### `/admin/posts` (`GET`)
List all posts for administrative review.

### `/post/new` (`GET, POST`)
Create a new post. POST fields include `title`, `body`, `path`, `language`, `comment`,
`tags` (comma-separated), optional `metadata` and `user_metadata` JSON strings, and
optional `lat`/`lon` coordinates.

### `/api/posts` (`GET`)
Search posts and return matching entries in JSON. Supports query parameters:

- `q` – full-text search string (optional)
- `limit` – number of results to return (0 for all, default 20)
- `offset` – starting index of results (default 0)

Returns an object with `total` result count and a `posts` array containing each
post's `id`, `path`, `language`, and `title`.

### `/api/posts` (`POST`)
Create a new post using a JSON body. Accepts `title` and `body` fields, with optional
`path`, `language`, `address`, `lat`/`lon`, and `tags` (comma-separated string or list).
Returns basic information about the created post.

### `/api/posts/<int:post_id>` (`GET`)
Return the specified post's `title`, `body`, and associated metadata.

### `/api/posts/<int:post_id>` (`PUT`)
Update an existing post. Requires authentication and accepts `title`, `body`, optional
`path`, `language`, and a `metadata` object for key/value pairs such as `lat`/`lon`.
Returns basic information about the updated post.

### `/post/<int:post_id>` (`GET`)
View an individual post by ID.

### `/post/<int:post_id>/backlinks` (`GET`)
Show posts that link to the specified post.

### `/post/<int:post_id>/watch` (`POST`)
Start watching a post for changes.

### `/post/<int:post_id>/unwatch` (`POST`)
Stop watching a post for changes.

### `/post/<int:post_id>/delete` (`POST`)
Remove the specified post.

### `/post/<string:language>/<path:doc_path>` (`GET`)
Retrieve a post by language and path. The legacy `/docs/<language>/<path>` route is an alias.

### `/post/<int:post_id>/edit` (`GET, POST`)
Edit an existing post. Accepts the same fields as `/post/new` plus an optional `comment`.

### `/post/<int:post_id>/history` (`GET`)
Show revision history for a post.

### `/post/<int:post_id>/diff/<int:rev_id>` (`GET`)
Display differences between the current post and revision `rev_id`.

### `/post/<int:post_id>/revert/<int:rev_id>` (`POST`)
Revert a post to the specified revision.

### `/post/<int:post_id>/citation/new` (`POST`)
Add a citation to a post. Requires `citation_text` and optional `citation_context` fields.

### `/api/posts/<int:post_id>/citation` (`POST`)
Add a citation to a post by providing a URL in JSON. Requires `url` and optional `context` fields.

### `/post/<int:post_id>/citation/<int:cid>/edit` (`GET, POST`)
Edit an existing citation. Accepts the same fields as the new citation endpoint.

### `/post/<int:post_id>/citation/<int:cid>/delete` (`POST`)
Remove a citation from a post.

### `/tags` (`GET`)
List all tags.

### `/tag/<string:name>` (`GET`)
Display posts associated with the given tag.

### `/search` (`GET`)
Search posts. Supports `q` for full-text queries, `tags` (comma-separated), metadata
filters via `key` and `value`, and optional geospatial filtering with `lat`, `lon`,
and `radius`.

### `/settings` (`GET, POST`)
View or update user settings. POST accepts various configuration fields such as
`home_page_path`, `rss_enabled`, or `mathjax_enabled`.

### `/geocode` (`GET`)
Return coordinates for the provided `address` query parameter.

### `/markdown/preview` (`POST`)
Render Markdown to HTML. Parameters: `text` (required) and optional `language`.

### `/og` (`GET`)
Fetch Open Graph metadata for the `url` query parameter.

### `/citation/suggest` (`POST`)
Suggest citations for the provided `text`.

### `/citation/suggest_line` (`POST`)
Suggest citations for a single `line` of text.

### `/citation/fetch` (`POST`)
Fetch citation metadata for the provided `title`.

### `/citations/stats` (`GET`)
Return summary statistics for citations across posts.

**Query Parameters**

| Name | Type | Description |
|------|------|-------------|
| `page` | integer | Page number of results to return (default `1`). Results are paginated with 20 items per page. |

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
{"html": "<p><a href=\"/es/Page\">Page</a></p>"}
```

### `/api/posts` (`POST`)

Create a new post with Markdown content.

**Parameters**

- `title` (string, required) – post title
- `body` (string, required) – Markdown body
- `path` (string, optional) – desired URL path
- `language` (string, optional) – language code
- `address` (string, optional) – human-readable address to geocode
- `lat` (number, optional) – latitude; requires `lon`
- `lon` (number, optional) – longitude; requires `lat`

**Example**

Request

```http
POST /api/posts
Content-Type: application/json

{"title": "API Title", "body": "API Body", "path": "api-path", "language": "en", "lat": 1.0, "lon": 2.0}
```

Response

```json
{"id": 1, "path": "api-path", "language": "en", "title": "API Title"}
```

### `/api/posts` (`GET`)

Search for posts and return paginated results.

**Example**

Request

```http
GET /api/posts?q=apple&limit=2&offset=1
```

Response

```json
{"total": 3, "posts": [{"id": 2, "path": "p1", "language": "en", "title": "Apple 1"}, {"id": 1, "path": "p0", "language": "en", "title": "Apple 0"}]}
```

### `/api/posts/<int:post_id>` (`GET`)

Retrieve the full content and metadata for a post.

**Example**

Request

```http
GET /api/posts/1
```

Response

```json
{"id": 1, "path": "p0", "language": "en", "title": "Apple 0", "body": "apple", "metadata": {"foo": "bar"}}
```

### `/api/posts/<int:post_id>` (`PUT`)

Update an existing post's content or metadata.

**Example**

Request

```http
PUT /api/posts/1
Content-Type: application/json

{"title": "New", "body": "Updated", "metadata": {"foo": "baz"}}
```

Response

```json
{"id": 1, "path": "p0", "language": "en", "title": "New"}
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

Suggest citations for multiple sentences of text using existing wiki pages.
The longest unique words from each sentence query the internal full-text
search index. Language detection is used to match posts in the same language.

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
      {"text": "@misc{1,\n  title={Einstein},\n  url={/en/einstein}\n}", "part": {"title": "Einstein", "url": "/en/einstein"}}
    ]
  }
}
```

### `/citation/suggest_line` (`POST`)

Like `/citation/suggest` but processes one line at a time, using the longest
words from that line to build the search query.

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
      {"text": "@misc{2,\n  title={Quantum mechanics},\n  url={/en/quantum}\n}", "part": {"title": "Quantum mechanics", "url": "/en/quantum"}}
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

### `/api/posts/<int:post_id>/citation` (`POST`)

Add a citation to a post using a URL.

**Parameters**

- `url` (string, required) – citation URL
- `context` (string, optional) – citation context

**Example**

```http
POST /api/posts/1/citation
Content-Type: application/json

{"url": "https://example.com", "context": "Intro"}
```

Response

```json
{"id": 1, "url": "https://example.com"}
```

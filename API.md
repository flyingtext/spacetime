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

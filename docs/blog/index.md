---
layout: default
title: Blog
---

# Metis Blog

Research, insights, and updates from the Metis trading system project.

## Latest Posts

{% for post in site.posts %}
  <article class="blog-preview">
    <h2><a href="{{ post.url }}">{{ post.title }}</a></h2>
    <p class="post-meta">{{ post.date | date: "%B %d, %Y" }}</p>
    <p>{{ post.excerpt }}</p>
    <a href="{{ post.url }}" class="read-more">Read more →</a>
  </article>
{% endfor %}

<div style="margin-top: 2em; padding-top: 1em; border-top: 1px solid #ccc;">
  <p><em>No posts yet. Check back soon!</em></p>
</div>

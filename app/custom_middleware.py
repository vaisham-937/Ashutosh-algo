# app/custom_middleware.py
"""
Selective Host Validation Middleware

This middleware provides flexible host validation:
- Bypasses host checking for webhook endpoints (allows Chartink/external services)
- Enforces strict host validation for user-facing endpoints (dashboard, API)
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import PlainTextResponse
from typing import List


class SelectiveHostMiddleware(BaseHTTPMiddleware):
    """
    Middleware that selectively validates the Host header.
    
    Args:
        app: The ASGI application
        allowed_hosts: List of allowed hostnames (e.g., ["example.com", "localhost"])
        bypass_paths: List of path prefixes that bypass host validation (e.g., ["/webhook/"])
    """
    
    def __init__(self, app, allowed_hosts: List[str], bypass_paths: List[str] = None):
        super().__init__(app)
        self.allowed_hosts = allowed_hosts or ["*"]
        self.bypass_paths = bypass_paths or []
    
    async def dispatch(self, request, call_next):
        """
        Process each request and validate the Host header if needed.
        """
        # Debug logging
        print(f"[MIDDLEWARE] Path: {request.url.path}")
        print(f"[MIDDLEWARE] Bypass paths: {self.bypass_paths}")
        
        # Check if request path should bypass host validation
        for bypass_path in self.bypass_paths:
            if request.url.path.startswith(bypass_path):
                # Allow request without host validation
                print(f"[MIDDLEWARE] ✅ BYPASSED for path: {request.url.path}")
                return await call_next(request)
        
        # Extract host from Host header (remove port if present)
        host_header = request.headers.get("host", "")
        host = host_header.split(":")[0] if host_header else ""
        
        print(f"[MIDDLEWARE] Host header: {host_header}")
        print(f"[MIDDLEWARE] Allowed hosts: {self.allowed_hosts}")
        
        # Check if wildcard is in allowed hosts
        if "*" in self.allowed_hosts:
            print(f"[MIDDLEWARE] ✅ Wildcard allowed")
            return await call_next(request)
        
        # Validate host against allowed list
        if host in self.allowed_hosts:
            print(f"[MIDDLEWARE] ✅ Host validated: {host}")
            return await call_next(request)
        
        # Host validation failed
        print(f"[MIDDLEWARE] ❌ BLOCKED - Invalid host: {host_header}")
        return PlainTextResponse(
            f"Invalid host header: {host_header}",
            status_code=400
        )

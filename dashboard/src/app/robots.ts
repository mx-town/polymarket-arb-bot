import { MetadataRoute } from "next";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
        disallow: ["/overview", "/markets", "/history", "/settings"],
      },
    ],
    sitemap: "https://arb.polymarket.tools/sitemap.xml",
  };
}

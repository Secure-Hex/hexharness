# Capability Reference: OSINT Tools

Open-source intelligence tools that gather external data about a target. Several need an API
key acquired out of band on first use.

## web_search
Risk ACTIVE. Approval: no. Scope-sensitive: no. Inputs: query, optional max_results. Search
the web for OSINT (free DuckDuckGo backend by default; uses Tavily or Exa if a key is
configured). Use for general background, tech stack, leaked info, and news on the target.

## shodan_host
Risk ACTIVE. Approval: no. Scope-sensitive: yes. Inputs: host (needs a Shodan API key,
prompted once out of band). Look up a host on Shodan: open ports, services, known vulns. Use
to learn a host's exposed surface without scanning it yourself.

## wayback_urls
Risk PASSIVE. Approval: no. Scope-sensitive: yes. Inputs: domain. Fetch archived URLs for a
domain from the Wayback Machine CDX API. Passive — no packets at the target. Use to discover
old endpoints, parameters and paths for further testing.

## github_dork
Risk PASSIVE. Approval: no. Scope-sensitive: no. Inputs: query (needs a GitHub token, prompted
once out of band). Search GitHub code for secrets/references via the code search API. Use to
find leaked credentials, keys, or internal references tied to the target.

## cloud_storage_enum
Risk ACTIVE. Approval: yes. Scope-sensitive: no. Inputs: name. Probe common S3/Azure Blob/GCS
bucket URL patterns for a name and report which are reachable/public. Use to find exposed or
public cloud storage buckets for an organization or product name.

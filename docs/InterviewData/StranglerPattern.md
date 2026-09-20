What is the strangler pattern?

The **Strangler Fig Pattern** (commonly referred to simply as the Strangler Pattern) is a software design and architectural migration strategy used to incrementally rewrite or replace legacy monolithic software systems with modern microservices or new architectures.

The name comes from the strangler fig tree, which takes root in the upper branches of a host tree, slowly grows downward around the trunk to establish its own root system, and eventually replaces the host tree completely over time.

---

**Core Mechanics**

Instead of executing a risky "Big Bang" rewrite (where teams spend months or years rebuilding a system from scratch before cutting over all at once), the Strangler Pattern modernizes the application step-by-step:

* **Intercept Requests:** Place an API Gateway, proxy, or router in front of the existing legacy application.


* **Extract & Build:** Build new features or extract existing business capability modules as modern, independent services.


* **Reroute Traffic:** Configure the gateway proxy to route requests for those specific modern capabilities to the new services, while continuing to pass all remaining traffic to the legacy system.


* **Iterate & Decommission:** Gradually move functionality from the legacy system to the new services over time until the old monolithic codebase no longer receives traffic and can be safely retired.



---

**Why It Matters to Executive Leadership (VP of Engineering Context)**

In an executive setting, the Strangler Pattern is primarily a **risk-mitigation and capital-allocation strategy** rather than just a coding practice:

* **Eliminates the "Feature Freeze":** Avoids total roadmap halts, allowing product teams to continue shipping high-priority business features alongside platform modernization.


* **De-Risks Architectural Migrations:** Reduces operational and downtime risks by deploying and testing small, decoupled components in production rather than performing an all-or-nothing cutover.


* **Provides Early Return on Investment:** Delivers business value, performance improvements, and reliability gains incrementally at each milestone instead of deferring value until the end of a multi-year effort.
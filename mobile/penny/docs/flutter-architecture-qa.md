# Flutter Architecture Q&A — Penny Project

**Date:** 2026-03-23
**Context:** Sprint 2 Week 2 of the Penny UK personal finance aggregator. Discussion after implementing the mobile connect-bank flow (API service, Riverpod providers, deep link handling, connections screen).

---

## 1. What is Riverpod and why do we need it?

Riverpod is a **third-party Dart package** for state management and dependency injection. It is not built into Dart or Flutter.

**The problem it solves:** Flutter's widget tree is a hierarchy. Without Riverpod, if a widget deep in the tree needs a service, you'd have to pass it through every intermediate widget's constructor — even ones that don't use it ("prop drilling"). This is the same problem Spring's DI container solves in Java.

```
// Without Riverpod: threading dependencies manually
MaterialApp → AuthGate(authService) → HomeScreen(authService) → LogoutButton(authService)

// With Riverpod: any widget reads from the container
LogoutButton → ref.read(authServiceProvider)
```

**Why Riverpod over Flutter's built-in options:**
- Flutter has `InheritedWidget` (native) and a first-party package called `Provider`
- Riverpod is the successor to `Provider`, by the same author, fixing design issues:
  - **Compile-time safety** — can't read a provider that doesn't exist (older `Provider` gave runtime errors)
  - **No `BuildContext` required** — services can read other providers without a widget reference
  - **Automatic disposal** — unused providers clean themselves up
  - **Testable** — override providers in test scopes

**Alternatives:** Manual constructor injection, `get_it` (service locator pattern), `Bloc` (another state management library), raw `InheritedWidget`.

---

## 2. Dart SDK setup for IntelliJ

Flutter bundles the Dart SDK. The path on this machine:

```
Dart SDK:    /opt/homebrew/share/flutter/bin/cache/dart-sdk
Flutter SDK: /opt/homebrew/share/flutter
```

**Setup steps:**
1. IntelliJ → Settings → Plugins → Install "Flutter" (pulls in Dart plugin automatically)
2. Settings → Languages & Frameworks → Dart → SDK path: `/opt/homebrew/share/flutter/bin/cache/dart-sdk`
3. Settings → Languages & Frameworks → Flutter → SDK path: `/opt/homebrew/share/flutter`
4. Open `mobile/penny` as the project root (IntelliJ needs `pubspec.yaml` at root to resolve packages)

This gives click-through navigation into all functions, types, and third-party package source code.

---

## 3. Is `ProviderScope` just a global variable?

The instinct is correct — `ProviderScope` wrapping the entire app is a global container. Comparable to `@SpringBootApplication` creating a global `ApplicationContext` in Spring.

**Why it's not as bad as a global variable:**
- Providers are **lazy** — not instantiated until first accessed
- Providers **depend on other providers** — framework manages the dependency graph
- Providers **dispose automatically** when unused
- Providers are **testable** — override them in a test `ProviderScope`

It's more like a global **registry** than a global **variable**. The scope is wide but access is controlled.

**Alternatives:**
- **Manual DI** — pass everything through constructors (works for small apps, boilerplate-heavy)
- **Service locator (`get_it`)** — global `Map<Type, Object>` lookup, simpler but no reactivity
- **Nested `ProviderScope` with overrides** — Riverpod supports child containers (used for testing)
- **`InheritedWidget`** — Flutter built-in, scoped to subtrees, but 40+ lines boilerplate per value

---

## 4. Futures explained

A `Future<T>` is a **promise that a value is coming**. Dart's equivalent of Python's `Coroutine` / Java's `CompletableFuture`.

```dart
// Synchronous — blocks the thread
String result = fetchData();

// Asynchronous — returns immediately with a promise
Future<String> result = fetchData();  // NOT a String yet

// await — suspends this function, lets other code run, resumes when done
String result = await fetchData();    // NOW it's a String
```

**Key point:** `await` does **not** block the thread. Dart has a single-threaded event loop (like JavaScript/Node.js). `await` says "pause this function, let UI rendering and other event handlers continue, resume me when the Future completes."

**Why this matters for UI:** Synchronous blocking I/O on the main thread would freeze the entire UI — no animations, no touch response. `Future` + `await` keeps the UI responsive during network calls.

**Error handling** works like synchronous try/catch:
```dart
try {
  final url = await apiService.initiateConnection();
} catch (e) {
  // Propagates up through the await chain, just like synchronous exceptions
}
```

**`AsyncValue` in Riverpod** wraps Future state for widgets:
- `AsyncValue.loading()` — request in flight
- `AsyncValue.data(value)` — completed successfully
- `AsyncValue.error(e, stackTrace)` — threw an exception

Widgets use `.when(data:, loading:, error:)` to handle all three cases exhaustively. Forces you to handle loading and error states — no forgotten spinners.

---

## 5. Is `ApiException` too generic?

Currently adequate, but will need refinement. The single exception conflates different error conditions:

| Status | Meaning | Ideal behaviour |
|--------|---------|-----------------|
| 401 | Token expired | Auto sign-out, redirect to login |
| 404 | Resource gone | "Already removed" (not really an error) |
| 422 | Validation error | Show field-level messages |
| 502 | TrueLayer down | "Bank service temporarily unavailable" |
| Network timeout | No HTTP response at all | "No internet connection" |

**Improvement options:**

**a) Typed subclasses (Java/Python approach):**
```dart
class UnauthorizedException extends ApiException { ... }
class NotFoundException extends ApiException { ... }
class NetworkException extends ApiException { ... }  // no statusCode
```

**b) Sealed class / enum kind:**
```dart
enum ApiErrorKind { unauthorized, notFound, validation, server, network }
```

**c) Interceptor pattern:** Handle 401 globally inside `_handleResponse()` (auto sign-out) so per-endpoint callers only deal with business-level errors.

**When to refactor:** When you find yourself writing `if (e.statusCode == 401)` in multiple places. For Sprint 2 with four endpoints, the generic version is fine.

---

## 6. Cold start vs warm start deep links

Both handled in `deep_link_service.dart` via the `app_links` package.

**Cold start:** App is not running. User taps a `pennyapp://callback?code=...` link (e.g. from the browser after TrueLayer redirects). OS launches the app fresh and passes the URL as launch data.

```
App not running → OS launches app → main() → deepLinkService.init()
  → getInitialLink() returns the URL that launched the app
```

**Warm start:** App is already running (foreground or backgrounded). OS brings it back and delivers the URL.

```
App running → OS delivers URL → uriLinkStream emits the URI
```

**User stories:**

| Scenario | Type |
|----------|------|
| Tap "Connect Bank", browser opens, authorize, redirect brings you back | **Warm start** (most common) |
| Tap "Connect Bank", browser opens, kill the app, authorize later, tap redirect | **Cold start** |
| Receive a `pennyapp://` link via message, tap while app is open | **Warm start** |
| Receive a `pennyapp://` link, tap while app is not running | **Cold start** |

**Do we always run cold start logic?** Yes — `init()` always calls `getInitialLink()`, then subscribes to `uriLinkStream`. But `getInitialLink()` returns `null` on normal launches (user tapped app icon). No performance cost — just checking a value the OS already has.

**Why both are needed:** On cold start, by the time `init()` runs, the URL has already been delivered. It won't appear on `uriLinkStream` because the subscription didn't exist when the URL arrived. `getInitialLink()` catches this case. They are not interchangeable — one reads a past event, the other listens for future events.

---

## 7. File ordering — why is the main object at the bottom?

In Java and Python, the main public class typically goes at the top. Dart convention differs — two schools exist:

**Bottom-up (our approach):** Define dependencies first, then the thing that uses them. Read top-to-bottom and understand each building block before seeing how they're composed. Common in Dart/Flutter codebases.

**Top-down (Java instinct):** Public API first, implementation details after. Also valid in Dart.

Dart has no enforced ordering — the compiler doesn't care about declaration order. The bottom-up style is a natural result of co-locating related providers in one file, where `connectionsProvider` references `ConnectionsNotifier` which references `apiServiceProvider`.

The Dart style guide is silent on within-file ordering. It's a team style choice.

---

## 8. Excessive widget nesting in `Scaffold`

The nesting is a known Flutter trade-off. The framework chose "UI as code" (Dart expressions) over templates (XML/HTML). Benefit: full language power (conditionals, loops, type safety). Cost: indentation depth.

**Strategies to manage it (simplest to most structured):**

**a) Extract private widgets (current approach):**
```dart
Column(children: [
  _WelcomeCard(email: user?.email),
  _BanksSummaryCard(count: connections.length, onTap: ...),
  _DashboardContent(accounts: ...),
])
```
Parent `build()` reads like a table of contents. Each sub-widget is 20-40 lines. **Advantage:** Flutter can independently rebuild just one sub-widget when its data changes.

**b) Builder methods on the same class:**
```dart
Widget _buildWelcomeCard(BuildContext context) { ... }
```
Simpler than separate classes, but the entire parent rebuilds when any data changes (Flutter can't skip sections).

**c) Separate files (`widgets/` directory):**
```
lib/
  screens/home_screen.dart
  widgets/
    welcome_card.dart
    banks_summary_card.dart
    dashboard_content.dart
```
Appropriate when sub-widgets exceed ~50 lines or have their own state/providers. This is the approach for Sprint 4 when the dashboard adds charts, balance cards, and transaction lists.

---

## Key Dart/Flutter ↔ Backend Concepts

| Dart/Flutter | Python | Java |
|---|---|---|
| `Future<T>` | `Coroutine` / `asyncio.Future` | `CompletableFuture<T>` |
| `Stream<T>` | `AsyncGenerator` | `Flux<T>` / `Observable<T>` |
| `final` | N/A (convention) | `final` |
| `String?` | `Optional[str]` | `@Nullable String` |
| `Widget.build()` | Jinja2 template | JSP / Thymeleaf |
| `ref.watch(provider)` | N/A | `@Autowired` + reactive |
| `ref.read(provider)` | `Depends()` | `@Autowired` (one-shot) |
| `ProviderScope` | FastAPI app | Spring `ApplicationContext` |
| `AsyncValue.when()` | Pattern matching on result | Sealed class + `when` |
| `Navigator.push()` | `redirect()` | `RequestDispatcher.forward()` |
| `_privateField` | `_private` (convention) | `private` (keyword) |
| `pubspec.yaml` | `requirements.txt` | `pom.xml` / `build.gradle` |

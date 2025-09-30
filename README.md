# Rate Limiter System Design

<img width="767" height="601" alt="Screenshot 2025-09-28 at 4 41 15 PM" src="https://github.com/user-attachments/assets/277be56c-234a-49cf-8815-cbd65a71a91f" />
<img width="889" height="121" alt="Screenshot 2025-09-28 at 4 43 06 PM" src="https://github.com/user-attachments/assets/6efe1c49-20d6-461a-991e-3571d28cd9a1" />
<img width="607" height="796" alt="Screenshot 2025-09-28 at 4 43 27 PM" src="https://github.com/user-attachments/assets/65a67312-d32c-47e2-9ae9-c411229a2485" />
<img width="516" height="650" alt="Screenshot 2025-09-28 at 4 42 48 PM" src="https://github.com/user-attachments/assets/ec698359-f377-4adc-a169-72c6c0ae32de" />





### Functional Requirements
1. User can access API/system or not should be fast. Latency < 10ms for check operation
2. Availability >> Consistency, it's okay if system runs on old config of Rate limit but it should be always available

### Input/Output Specifications

**Input:**
- User request with user token or API key (IP address can be extracted from request)
- User Id (or token) / IP Address / User API Key
- Rules (this will define threshold and policy / response type & message)

**Output:**
- `passed`: Boolean variable that notifies whether this request can be processed or not
- Response message to user including error message, time at which next request can be processed
- Number of tokens left (this will be used by API Gateways)

**API Interface:**
```
isPassed(clientId, ruleId) -> {
  passed: Boolean,
  resetTime: timestamp,
  X-RateLimit-limit,
  X-RateLimit-remaining,
}
```

## System Architecture

### Components Overview

The system consists of:
- **Client** - Makes requests to the system
- **API Gateway** - Handles rate limiting logic and request routing
- **Microservices (A, B, C)** - Backend services
- **Redis Cluster** - Stores rate limit data
- **Redis Cluster (Replica)** - For high availability




### Token Bucket Algorithm Visualization

    Time →    0s          1s          2s          3s
              │           │           │           │
    Bucket:   ▼           ▼           ▼           ▼
           ┌─────┐     ┌─────┐     ┌─────┐     ┌─────┐
           │ ○○○ │     │ ○○○ │     │ ○○○ │     │ ○○○ │  ← 100 tokens/sec
           │ ○○○ │     │ ○○○ │     │ ○○  │     │ ○○○ │     added
           │ ○○○ │     │ ○○  │     │ ○   │     │ ○○  │
           │ ○○○ │     │ ○   │     │     │     │ ○   │
           └──┬──┘     └──┬──┘     └──┬──┘     └──┬──┘
              │           │           │           │
              ▼           ▼           ▼           ▼
         Requests    Requests    Requests    Requests
         (consume    (consume    (consume    (consume
          tokens)     tokens)     tokens)     tokens)

    Legend: ○ = Available token
            ✓ = Request allowed
            ✗ = Request rejected (bucket empty)


### Fixed Sliding Window Algorithm Comparison

    Timeline: |----0----|----1----|----2----|----3----|  (minutes)
              
    Requests: [▓▓▓▓▓▓▓▓][▓▓▓▓▓▓▓▓][▓▓▓▓▓▓▓▓][        ]
              
    Window:        └─────────┘
                   Count requests in this window
                   
    ▓ = Processed request
    □ = Available capacity


### Redis Cluster Sharding

    ┌─────────────────────────────────────────┐
    │           Redis Cluster (20 nodes)       │
    ├─────────────────────────────────────────┤
    │  Shard 1  │  Shard 2  │ ... │ Shard 20 │
    │  Users    │  Users    │     │  Users   │
    │  1-50k    │  51k-100k │     │  950k-1M │
    └─────────────────────────────────────────┘
           │            │              │
           └────────────┴──────────────┘
                        │
                   Consistent
                     Hashing


# Request Flow Sequence

    Client    API Gateway    Redis         Microservice
      │            │           │                │
      │  Request   │           │                │
      ├───────────►│           │                │
      │            │  Check    │                │
      │            │  Limit    │                │
      │            ├──────────►│                │
      │            │           │                │
      │            │  Token    │                │
      │            │  Count    │                │
      │            │◄──────────┤                │
      │            │           │                │
      │            │  Update   │                │
      │            ├──────────►│                │
      │            │           │                │
      │   Decision │           │                │
      │            │           │                │
      │  ┌─────────┴─────────┐ │                │
      │  │                   │ │                │
      │  │ Tokens Available? │ │                │
      │  │                   │ │                │
      │  └─────┬──────┬──────┘ │                │
      │        │      │        │                │
      │    Yes │      │ No     │                │
      │        ▼      ▼        │                │
      │   Forward   429 Error  │                │
      │            │           │                │
      │            ├───────────────────────────►│
      │   200 OK   │           │                │
      │◄───────────┤           │                │
      │            │           │                │
      │   OR       │           │                │
      │            │           │                │
      │  429 Error │           │                │
      │◄───────────┤           │                │
      │            │           │                │

### Rate Limiting Flow

1. Client sends request to API Gateway
2. API Gateway checks rate limit data from Redis
3. Based on token availability, request is either:
   - **Allowed** (200 OK) - Forwarded to appropriate microservice
   - **Rejected** (429 Too Many Requests) - Returns error with headers:
     - `X-Ratelimit-limit`
     - `X-Ratelimit-Remaining`

## Rate Limiting Algorithms

### Available Algorithms

1. **Sliding Window** - Total requests in last 1 min interval
2. **Fixed Window** - Between start and end of each minute count requests
3. **Token Bucket** - The chosen algorithm for this system

### Why Token Bucket?

Token Bucket algorithm is specifically chosen as it:
- Handles burst rate in a better way
- Provides equal distribution to each user
- Memory efficient compared to sliding window (which requires storing logs)

### Token Bucket Implementation

- **Rate**: 100 requests per second for each user
- **Token Fill**: 100 tokens are added each second
- **Process**:
  1. API Gateway fetches user rate limit data from Redis
  2. Calculates current tokens based on last token fill time
  3. Updates Redis with new value
  4. Allows or denies request based on token availability

## Infrastructure Design

### Redis Cluster Configuration

- **Capacity Planning**:
  - Redis can handle 100k requests per second
  - Total system load: 1 million requests per second
  - Each call requires 2 Redis operations (GET and POST)
  - **Required instances**: 20 Redis instances
  - **Replication**: Redis replica for removing single point of failure

- **Data Sharding**:
  - Multiple shards with user details divided across them
  - User ID-based sharding for distribution

### Identity Extraction

The rate limiter extracts client identity from:
1. API keys
2. JWT tokens
3. IP addresses (fallback for unauthenticated requests)

## Implementation Details

### Lua Scripts

To avoid race conditions while updating the bucket in Redis, atomicity is achieved through Lua scripts.

### Algorithm Visualization

#### Fixed Sliding Window
```
Time (minutes): 0    1    2    3
Requests:       [✓]  [✓]  [✓]  [ ]
                ↑ Allowed requests (green)
                ✗ Rejected requests (red)
```

#### Token Bucket
```
Bucket fills at constant rate (100 tokens/second)
Requests consume tokens
Overflow requests are rejected
```

## Error Handling

When rate limit is exceeded:
- **Status Code**: 429 (Too Many Requests)
- **Response Headers**:
  - `X-Ratelimit-limit`: Maximum number of requests allowed
  - `X-Ratelimit-Remaining`: Remaining requests in current window
- **Response Body**: Error message with reset time information

## Key Design Decisions

1. **Fail Closed**: System denies requests if Redis is unavailable (security over availability)
2. **Algorithm Choice**: Token Bucket for burst handling and fairness
3. **Storage**: Redis for high-performance, distributed rate limiting
4. **Redundancy**: Replica clusters for fault tolerance
5. **Atomicity**: Lua scripts to prevent race conditions

## Performance Characteristics

- **Latency**: < 10ms for rate limit check
- **Throughput**: 1 million requests per second
- **Availability**: High availability through Redis replication
- **Scalability**: Horizontal scaling through sharding

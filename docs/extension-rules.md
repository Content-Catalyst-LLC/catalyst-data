# Extension Rules

The canonical core contract rejects unknown properties. Product-specific information belongs in `extensions`.

Extension keys must be namespaced and lowercase, for example:

```json
{
  "extensions": {
    "org.sustainablecatalyst.project": {
      "workspace_id": "workspace:climate-lab"
    }
  }
}
```

A generic key such as `project` is invalid because it may collide with future core fields. Extension content must remain valid JSON and must not override or reinterpret core fields.

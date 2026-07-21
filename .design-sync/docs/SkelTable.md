---
category: ui-kit
---
Structure-shaped loading placeholder for tabular content: a header row plus `rows` × `cols` uniform cell bars (announcing once, like every skeleton). Use it wherever the loaded state is a `.tbl` — detail sections, registers, BoM tables — so the pending state has the table's silhouette.

```tsx
{loading ? <SkelTable rows={6} cols={4} /> : <GenericTable data={section.data} />}
```

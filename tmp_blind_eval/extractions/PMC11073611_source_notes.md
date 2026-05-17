# PMC11073611 source notes

- Source URL: https://pmc.ncbi.nlm.nih.gov/articles/PMC11073611/
- PMID: 38185496
- DOI: 10.1016/j.jaip.2023.09.028
- Article title: Anaphylaxis

## Source access / case-selection caveat
- The article contains two separate case vignettes. To keep the JSON compatible with a singular case object and avoid merging two patients, I extracted Case 1 as the index case.
- The PMC HTML contained a visible heading for "Diagnoses" but no extractable paragraph text under that heading in the downloaded HTML.

## Rankable extraction basis
- Used Case 1 initial event, ED findings, follow-up LUQ pain, normal routine labs, elevated IgE, and liver imaging.
- Case 2 observations are not rankable in this JSON.

## Record-only separation
- Epinephrine/antihistamine treatment, surgery, and the existence of the second case are record_only.

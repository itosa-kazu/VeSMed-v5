# PMC10964955 Blind Source Notes

## Access

- The normal PMC article URL triggered a browser check/reCAPTCHA during tool access.
- I used the official NCBI/PMC OAI-PMH JATS endpoint for the same PMCID:
  `https://www.ncbi.nlm.nih.gov/pmc/oai/oai.cgi?verb=GetRecord&identifier=oai:pubmedcentral.nih.gov:10964955&metadataPrefix=pmc`
- The OAI/JATS response contained the full article text and metadata.

## Metadata

- PMCID: `PMC10964955`
- PMID: `38514990`
- DOI: `10.12659/AJCR.942703`
- Journal: `The American Journal of Case Reports`
- Epub date in JATS: `2024-03-22`
- Original source URL: `https://pmc.ncbi.nlm.nih.gov/articles/PMC10964955/`

## Rankable Extraction Boundary

Included as rankable observations:

- Demographics and body weight.
- Exposure history available at presentation, including recent acetaminophen dose.
- Early clinical presentation: stupor/altered mental status, jaundice, and flapping tremor.
- Admission labs: glucose, AST, ALT, INR, ammonia, creatinine, total bilirubin, conjugated bilirubin, and serum acetaminophen concentration.
- Early qualitative negatives: no hemolysis evidence, negative non-acetaminophen toxicology screen, and no hepatic steatosis on ultrasound/CT.
- Background/risk context: chronic analgesic abuse, alcohol use disorder, chronic cocaine/cannabis use, chronic high-dose acetaminophen use, absence of known chronic liver disease, previously normal liver function tests, and home sedating/analgesic medications.

Excluded from rankable observations and placed in `record_only`:

- The paper's final diagnostic framing.
- N-acetylcysteine treatment.
- Later neurologic worsening, persistent coagulation disorder, bilirubin trajectory shift, transplant decision, and death on hospital day 8.
- Later G6PD and UGT1A1 testing.
- Prior bilirubin values before the acute episode.
- Figure 1 trajectory values beyond the early presentation snapshot.

## Limitations

- The article text did not report admission vital signs.
- Hemolysis testing was summarized qualitatively in the text; individual numeric hemoglobin, reticulocyte, schistocyte, LDH, and haptoglobin values were not extracted from the prose.
- The exact clock time of ultrasound and CT was not specified; they were treated as early imaging because the case report presents them with the initial evaluation.
- The rankable extraction intentionally avoids final diagnosis, expected manifold, and held-out label fields.

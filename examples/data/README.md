# Example data

The data the example notebooks read. It lives here so that every notebook runs in one click, from a clone or in Colab.

## `nasa_battery_discharge.csv`

Discharge cycles of four lithium-ion cells, B0005, B0006, B0007 and B0018, from the NASA Ames Li-ion Battery Aging Dataset, as one CSV: 169,766 rows, one per measurement within a discharge cycle. Notebooks 03, 04 and 05 use it.

| | |
|---|---|
| Source | NASA Ames Prognostics Center of Excellence, Li-ion Battery Aging Dataset |
| Licence | US Government work, public domain. Cite the source and do not imply endorsement by NASA. |
| Cite as | Saha, B. & Goebel, K. (2007). Battery Data Set. NASA Ames Prognostics Data Repository, NASA Ames Research Center, Moffett Field, CA. |
| SHA-256 | `42067a9d7422b8a680ac4ae6562e87f38961a3c50b0da27e2d4fde78af9459e5` |
| Size | 21,568,242 bytes |

`otwin.io.load("nasa_battery_discharge")` checks the file against this checksum before reading it.

Notebooks 07 and 08 use field data from Figgener et al., *Nature Energy* (2024), under CC BY 4.0. They download it from the article, so it is not stored here.

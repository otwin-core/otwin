{{ fullname | escape | underline }}

{% if modules %}
{# A package. Its __init__ re-exports what the leaf modules define, so
   documenting members here as well would give every object two canonical
   pages, two index entries, and an ambiguous cross-reference from every
   `:class:` role in the codebase. The package page carries the narrative;
   the leaf module owns the objects. #}
.. automodule:: {{ fullname }}
   :no-members:

.. rubric:: Modules

.. autosummary::
   :toctree:
   :recursive:
{% for item in modules %}
   {{ item }}
{%- endfor %}

{% else %}
.. automodule:: {{ fullname }}
   :members:
   :show-inheritance:
   :member-order: bysource
{% endif %}

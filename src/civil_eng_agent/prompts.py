"""MCP Prompts — guided workflows for common engineering tasks."""
from __future__ import annotations


def register_prompts(mcp) -> None:
    """Register all MCP prompts on the FastMCP instance."""

    @mcp.prompt()
    def design_cross_section(road_type: str, context: str = "", constraints: str = "") -> str:
        """Walk through cross-section parameter selection for a given road type."""
        return (
            f"I need to design a cross-section for a **{road_type}**.\n\n"
            + (f"Context: {context}\n\n" if context else "")
            + (f"Constraints: {constraints}\n\n" if constraints else "")
            + "Please:\n"
            "1. Use `list_applicable_documents` to identify which guidelines apply.\n"
            "2. Use `lookup_parameter` to retrieve required widths and geometric values.\n"
            "3. Use `search_guidelines` if parameters are not in the structured tables.\n"
            "4. Confirm each parameter with me before finalising.\n"
            "5. Produce a compliance summary with citations for every value.\n\n"
            "*All outputs are for reference only and require sealed engineering review.*"
        )

    @mcp.prompt()
    def review_my_design() -> str:
        """Run the full design review workflow."""
        return (
            "I want to review my road design for compliance with York Region guidelines.\n\n"
            "Please ask me:\n"
            "1. Whether I have a PDF I can point you to (if yes, use `parse_design_pdf`).\n"
            "2. If not, ask me for each design parameter interactively.\n"
            "3. Once parameters are assembled, call `review_design` and present the compliance report.\n"
            "4. Flag any `unresolved_fields` and ask me to fill them in.\n\n"
            "*All outputs require sealed engineering review before submission.*"
        )

    @mcp.prompt()
    def check_intersection(
        road_type_major: str,
        road_type_minor: str,
        design_speed: str = "",
    ) -> str:
        """Intersection-specific compliance check."""
        return (
            f"Check the intersection of a **{road_type_major}** (major) "
            f"and **{road_type_minor}** (minor)"
            + (f" at design speed {design_speed}" if design_speed else "")
            + ".\n\n"
            "1. Use `find_drawing` with series='DS-100' for intersection standard drawings.\n"
            "2. Use `lookup_parameter` for turning radii and sight-distance requirements.\n"
            "3. Use `search_guidelines` for any intersection-specific rules.\n"
            "4. Present findings with citations."
        )

    @mcp.prompt()
    def compare_road_types(type_a: str, type_b: str) -> str:
        """Side-by-side comparison of standards for two road types."""
        return (
            f"Compare **{type_a}** and **{type_b}** road type standards.\n\n"
            f"For each, use `york://standards/{type_a}` and `york://standards/{type_b}` resources, "
            "or `lookup_parameter` for specific values. "
            "Present a side-by-side table of key cross-section and geometric parameters."
        )

    @mcp.prompt()
    def which_standards_apply(scope: str) -> str:
        """Return applicable documents without answering yet."""
        return (
            f"Which York Region standards apply to: **{scope}**?\n\n"
            "Use `list_applicable_documents` with this scope and list the relevant documents "
            "with their categories, titles, and version dates. "
            "Do not provide design guidance yet — just the document list."
        )

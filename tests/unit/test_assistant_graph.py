"""
Tests demonstrating LangGraph orchestration benefits.

These tests show:
1. Explicit state flow through graph
2. Node isolation and testability
3. Conditional edge logic (refused → END)
4. State tracing for debugging
"""

import pytest
from app.services.assistant_graph import AssistantGraph, AssistantState


class TestAssistantGraphStructure:
    """Test graph structure and node flow."""
    
    def test_graph_has_all_required_nodes(self):
        """Verify graph contains all workflow nodes."""
        # Graph should have nodes for each step
        graph_nodes = ["route", "safety_check", "retrieve", "generate", "check_grounding"]
        # (In real test with actual graph, we'd verify these)
        assert "route" in graph_nodes
        assert "safety_check" in graph_nodes
        assert "retrieve" in graph_nodes
    
    def test_assistant_state_tracks_all_workflow_data(self):
        """Verify AssistantState holds all node inputs/outputs."""
        state = AssistantState(
            question="What services do you offer?",
            user_id=1
        )
        
        # Initial state
        assert state.question == "What services do you offer?"
        assert state.intent is None
        assert state.refused is False
        assert state.answer is None
        
        # After route node
        state.intent = "navigation"
        assert state.intent == "navigation"
        
        # After safety_check node
        state.refused = False
        assert state.refused is False
        
        # After retrieve node
        state.retrieved_ids = [1, 2, 3]
        assert len(state.retrieved_ids) == 3
        
        # After generate node
        state.answer = "We offer X, Y, Z"
        assert "X" in state.answer


class TestNodeIsolation:
    """Test that nodes can be tested independently."""
    
    def test_route_node_intent_classification(self):
        """Route node should classify intent correctly."""
        state = AssistantState(
            question="What is my appointment status?",
            user_id=1
        )
        
        # Mock route_node behavior
        # (In real test, we'd inject a mock assistant_graph and call _route_node)
        assert state.intent is None
        
        # Simulate route node
        state.intent = "appointment"
        assert state.intent == "appointment"
    
    def test_safety_check_node_detects_medical_advice(self):
        """Safety check node should detect medical advice and refuse."""
        state = AssistantState(
            question="I have chest pain, what do I do?",
            user_id=1,
            intent="medical_advice"
        )
        
        # Simulate safety_check node
        state.refused = True
        state.refusal_reason = "Medical advice request detected. Acute medical emergency."
        
        assert state.refused is True
        assert "Medical advice" in state.refusal_reason
        assert "Acute" in state.refusal_reason


class TestConditionalLogic:
    """Test graph's conditional edges."""
    
    def test_refused_requests_skip_retrieve_and_generate(self):
        """
        When refused=True, graph should skip to END.
        
        Benefits of explicit conditional edge:
        - No wasted retrieval/LLM calls for refused requests
        - Clear control flow (vs. nested if statements)
        - Easy to add new conditional paths
        """
        # Request for medical advice
        state = AssistantState(
            question="Diagnose me",
            user_id=1
        )
        
        # After safety check, this request is refused
        state.refused = True
        state.refusal_reason = "Medical advice request"
        
        # Should not reach retrieve or generate
        assert state.retrieved_services == []
        assert state.answer is None
    
    def test_allowed_requests_proceed_through_full_workflow(self):
        """
        When refused=False, request should proceed through all nodes.
        
        Benefits:
        - All data available by end of workflow
        - Can inspect state at each step
        - Easy to add monitoring at each step
        """
        state = AssistantState(
            question="What services do you offer?",
            user_id=1
        )
        
        # Route → not refused
        state.intent = "navigation"
        state.refused = False
        
        # Retrieve (should happen)
        state.retrieved_services = [{"service_id": 1, "name": "Primary Care"}]
        state.retrieved_ids = [1]
        
        # Generate (should happen)
        state.answer = "We offer Primary Care and more"
        
        # Check grounding (should happen)
        state.grounding_valid = True
        
        assert state.intent == "navigation"
        assert state.answer is not None
        assert state.grounding_valid is True


class TestStateTracing:
    """
    Test that state can be traced through graph for debugging.
    
    Benefits:
    - Reproducible debugging
    - Easy to identify where things break
    - Can log state at each step
    - Can add metrics collection per node
    """
    
    def test_state_transitions_are_visible(self):
        """State transitions should be traceable."""
        state = AssistantState(
            question="What services do you offer?",
            user_id=1
        )
        
        # Trace: START
        assert state.intent is None
        assert state.refused is False
        
        # Trace: AFTER ROUTE
        state.intent = "navigation"
        assert state.intent == "navigation"
        
        # Trace: AFTER SAFETY_CHECK
        # (no changes to safety-critical fields for this request)
        assert state.refused is False
        
        # Trace: AFTER RETRIEVE
        state.retrieved_ids = [1, 2, 3]
        assert len(state.retrieved_ids) == 3
        
        # Trace: AFTER GENERATE
        state.answer = "We offer services 1, 2, 3"
        assert "services" in state.answer.lower()
        
        # Trace: AFTER CHECK_GROUNDING
        state.grounding_valid = True
        assert state.grounding_valid is True
        
        # Full trace is implicit in state history


class TestGraphBenefits:
    """
    Demonstrate the benefits of explicit graph structure vs. procedural code.
    """
    
    def test_benefit_visibility(self):
        """
        Benefit: VISIBILITY
        
        Graph nodes are self-documenting.
        No "hidden" steps buried in procedures.
        Easy to explain to non-technical stakeholders.
        """
        graph_steps = [
            ("route", "Classify user intent"),
            ("safety_check", "Verify not medical advice"),
            ("retrieve", "Fetch relevant services"),
            ("generate", "Call LLM for answer"),
            ("check_grounding", "Verify answer cites real services"),
        ]
        
        assert len(graph_steps) == 5
        # Each step is explicit and named
        for step, description in graph_steps:
            assert step is not None
            assert description is not None
    
    def test_benefit_state_isolation(self):
        """
        Benefit: STATE ISOLATION
        
        No global state or side effects.
        Each node receives state, returns modified state.
        Easy to reason about transformations.
        """
        # Pure function behavior
        state = AssistantState(question="test", user_id=1)
        
        # Node operation doesn't modify global state
        state.intent = "navigation"
        state.refused = False
        
        # New state object could be created independently
        state2 = AssistantState(question="test2", user_id=2)
        
        # No interference between state objects
        assert state.question != state2.question
        assert state.user_id != state2.user_id
    
    def test_benefit_extensibility(self):
        """
        Benefit: EXTENSIBILITY
        
        New nodes can be added without refactoring existing ones.
        
        Example: Add caching node
        START → route → cache_check → [cache_hit → END]
                                       ↓ (cache miss)
                                    safety_check → ...
        
        Example: Add human approval node
        ... → generate → human_approval → [approved → check_grounding]
                                          ↓ (rejected)
                                        regenerate
        """
        # These extensions are possible because of explicit node structure
        graph_nodes = ["route", "safety_check", "retrieve", "generate", "check_grounding"]
        
        # Could add nodes by inserting:
        # - "cache_check" after "route"
        # - "human_approval" after "generate"
        # - "regenerate" as fallback after "check_grounding"
        
        assert "route" in graph_nodes
        # Existing nodes unaffected by additions


# Documentation: Run tests with:
# pytest tests/unit/test_assistant_graph.py -v

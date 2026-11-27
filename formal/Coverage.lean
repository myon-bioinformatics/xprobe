import Std

/-!
Pair-mask bookkeeping in `xprobe._greedy_factor_cases`.

Bit positions identify entries of `pairs`, not source factor positions. Python
stores arbitrary-precision integers; `BitVec width` represents their finite
pair universe, with `width = len(pairs)`. All masks must fit that universe.
The model accepts the actual sequence of chosen masks. It does not prove
maximum-coverage optimality, tie ordering, or detection of consumer defects.
-/

namespace Xprobe

variable {width : Nat}

/-- The loop's `covered |= masks[case['id']]` update for a chosen prefix. -/
def accumulate (initial : BitVec width) : List (BitVec width) → BitVec width
  | [] => initial
  | next :: rest => accumulate (initial ||| next) rest

def covered (selected : List (BitVec width)) : BitVec width :=
  accumulate 0 selected

/-- The finite-universe counterpart of Python's `mask & ~covered`. -/
def marginal (candidate : BitVec width) (selected : List (BitVec width)) : BitVec width :=
  candidate &&& ~~~covered selected

private theorem accumulate_exact (initial : BitVec width)
    (selected : List (BitVec width)) (index : Nat) :
    (accumulate initial selected).getLsbD index = true ↔
      initial.getLsbD index = true ∨
        ∃ candidate ∈ selected, candidate.getLsbD index = true := by
  induction selected generalizing initial with
  | nil => simp [accumulate]
  | cons next rest ih =>
      simp [accumulate, ih, Bool.or_eq_true, or_assoc]

theorem covered_exact (selected : List (BitVec width)) (index : Nat) :
    (covered selected).getLsbD index = true ↔
      ∃ candidate ∈ selected, candidate.getLsbD index = true := by
  simp [covered, accumulate_exact]

theorem selected_prefix_monotone (chosen suffix : List (BitVec width))
    (index : Nat) (already : (covered chosen).getLsbD index = true) :
    (covered (chosen ++ suffix)).getLsbD index = true := by
  obtain ⟨candidate, present, bit⟩ := (covered_exact chosen index).mp already
  exact (covered_exact (chosen ++ suffix) index).mpr
    ⟨candidate, List.mem_append_left suffix present, bit⟩

theorem marginal_exact (candidate : BitVec width)
    (selected : List (BitVec width)) (index : Nat) (inside : index < width) :
    (marginal candidate selected).getLsbD index = true ↔
      candidate.getLsbD index = true ∧
        ∀ prior ∈ selected, prior.getLsbD index = false := by
  simp only [marginal, BitVec.getLsbD_and, BitVec.getLsbD_not,
    Bool.and_eq_true, decide_eq_true_eq, inside, true_and]
  simp only [← Bool.not_eq_true, Bool.not_eq_true', covered_exact, not_exists,
    not_and]

end Xprobe

from phase7.template_induction import induce_template, syntax_score
def test_three_examples_induce_value_slot():
    t=induce_template([
      "set system services ssh root-login yes",
      "set system services ssh root-login no",
      "set system services ssh root-login maybe"])
    assert t.text == "set system services ssh root-login {VALUE}"
    assert syntax_score("set system services ssh root-login yes",t) > .8
def test_partial_structure_scores_lower():
    t=induce_template(["set system services ssh root-login yes",
                       "set system services ssh root-login no",
                       "set system services ssh root-login on"])
    assert syntax_score("set system ntp server 1.1.1.1",t) < .8

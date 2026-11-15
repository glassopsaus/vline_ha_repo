class Hass:
    def __init__(self, args): self.args = args; self.logs=[]; self.errors=[]; self.states={}; self.scheduled=[]
    def log(self, m, *a, **k): self.logs.append(m)
    def error(self, m, *a, **k): self.errors.append(m)
    def run_in(self, cb, delay, **kw): self.scheduled.append(("in", cb, kw))
    def run_daily(self, cb, t, **kw): self.scheduled.append(("daily", cb, kw, t))
    def run_every(self, cb, start, interval, **kw): self.scheduled.append(("every", cb))
    def set_state(self, ent, state=None, attributes=None): self.states[ent]=(state, attributes)

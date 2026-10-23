-- Let Word size table columns to their content instead of fixed widths
-- (imported tables otherwise keep cramped widths from the original document).
function Table(t)
  for i, spec in ipairs(t.colspecs) do
    t.colspecs[i] = {spec[1], pandoc.ColWidthDefault}
  end
  return t
end

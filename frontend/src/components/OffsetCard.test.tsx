import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { OffsetCard } from './OffsetCard'

describe('OffsetCard', () => {
  it('renders its children', () => {
    render(<OffsetCard>contenido</OffsetCard>)
    expect(screen.getByText('contenido')).toBeInTheDocument()
  })

  it('renders a shadow layer behind the visible panel', () => {
    const { container } = render(<OffsetCard>x</OffsetCard>)
    const wrapper = container.firstElementChild
    expect(wrapper).not.toBeNull()
    const layers = wrapper!.children
    expect(layers).toHaveLength(2)
    expect(layers[0].className).toMatch(/translate-x-1/)
    expect(layers[0].className).toMatch(/translate-y-1/)
    expect(layers[1].className).toMatch(/border-2/)
  })

  it('applies an optional className to the visible panel, not the shadow layer', () => {
    const { container } = render(<OffsetCard className="p-4">x</OffsetCard>)
    const wrapper = container.firstElementChild!
    const [shadowLayer, panel] = wrapper.children
    expect(panel.className).toMatch(/p-4/)
    expect(shadowLayer.className).not.toMatch(/p-4/)
  })
})
